"""Track list, search, detail, and CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

import asyncpg

from music_app.api.deps import get_conn
from music_app.api.models import (
    ScrobbleItem,
    ScrobbleList,
    TrackDetail,
    TrackItem,
    TrackList,
    TrackUpdate,
)

router = APIRouter()


def _row_to_item(row: asyncpg.Record) -> TrackItem:
    return TrackItem(
        id=row["id"],
        title=row["title"],
        album_title=row["album_title"],
        length_secs=row["length_secs"],
        artists=row["artists"] or [],
        scrobble_count=row["scrobble_count"],
        last_scrobbled=row["last_scrobbled"].isoformat() if row["last_scrobbled"] else None,
    )


@router.get("/tracks", response_model=TrackList)
async def list_tracks(
    q: str | None = Query(None),
    sort: str = Query("recent"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    conditions = []
    params: list = []
    idx = 1

    if q:
        conditions.append(f"(t.title_lower LIKE ${idx} OR EXISTS (SELECT 1 FROM track_artist ta2 JOIN artist a2 ON a2.id = ta2.artist_id WHERE ta2.track_id = t.id AND a2.name_lower LIKE ${idx}))")
        params.append(f"%{q.lower()}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    sort_map = {
        "recent": "last_scrobbled DESC NULLS LAST",
        "title": "t.title",
        "scrobbles": "scrobble_count DESC",
    }
    order = sort_map.get(sort, "last_scrobbled DESC NULLS LAST")

    total = await conn.fetchval(f"SELECT count(*) FROM track t {where}", *params)

    rows = await conn.fetch(f"""
        SELECT t.id, t.title, t.album_title, t.length_secs,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) AS artists,
               count(DISTINCT s.id) AS scrobble_count,
               max(s.listened_at) AS last_scrobbled
        FROM track t
        LEFT JOIN track_artist ta ON ta.track_id = t.id
        LEFT JOIN artist a ON a.id = ta.artist_id
        LEFT JOIN scrobble s ON s.track_id = t.id
        {where}
        GROUP BY t.id
        ORDER BY {order}
        LIMIT ${idx} OFFSET ${idx + 1}
    """, *params, limit + 1, offset)

    has_more = len(rows) > limit
    items = [_row_to_item(r) for r in rows[:limit]]
    return TrackList(items=items, total=total, has_more=has_more)


@router.get("/tracks/{track_id}", response_model=TrackDetail)
async def get_track(
    track_id: int,
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("""
        SELECT t.id, t.title, t.album_title, t.length_secs,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) AS artists,
               count(DISTINCT s.id) AS scrobble_count,
               max(s.listened_at) AS last_scrobbled
        FROM track t
        LEFT JOIN track_artist ta ON ta.track_id = t.id
        LEFT JOIN artist a ON a.id = ta.artist_id
        LEFT JOIN scrobble s ON s.track_id = t.id
        WHERE t.id = $1
        GROUP BY t.id
    """, track_id)

    if not row:
        raise HTTPException(404, "Track not found")

    # Enrichment data via scrobble link
    enrichment = await conn.fetchrow("""
        SELECT DISTINCT ON (mr.mbid)
               ma.genres AS artist_genres,
               mr.spotify_track_id, mr.tempo, mr.energy, mr.valence,
               mr.danceability, mr.acousticness, mr.instrumentalness,
               rg.title AS album_title_canonical,
               rg.first_release_year
        FROM track_artist ta
        JOIN artist a ON a.id = ta.artist_id
        JOIN music_scrobble_link sl ON sl.artist_string = a.name_lower
             AND sl.track_string = (SELECT title_lower FROM track WHERE id = $1)
        LEFT JOIN music_artist ma ON ma.mbid = sl.artist_mbid
        LEFT JOIN music_recording mr ON mr.mbid = sl.recording_mbid
        LEFT JOIN music_release_group rg ON rg.mbid = mr.release_group_mbid
        WHERE ta.track_id = $1
        LIMIT 1
    """, track_id)

    return TrackDetail(
        id=row["id"],
        title=row["title"],
        album_title=row["album_title"],
        length_secs=row["length_secs"],
        artists=row["artists"] or [],
        scrobble_count=row["scrobble_count"],
        last_scrobbled=row["last_scrobbled"].isoformat() if row["last_scrobbled"] else None,
        artist_genres=list(enrichment["artist_genres"]) if enrichment and enrichment["artist_genres"] else None,
        spotify_track_id=enrichment["spotify_track_id"] if enrichment else None,
        tempo=enrichment["tempo"] if enrichment else None,
        energy=enrichment["energy"] if enrichment else None,
        valence=enrichment["valence"] if enrichment else None,
        danceability=enrichment["danceability"] if enrichment else None,
        acousticness=enrichment["acousticness"] if enrichment else None,
        instrumentalness=enrichment["instrumentalness"] if enrichment else None,
        album_title_canonical=enrichment["album_title_canonical"] if enrichment else None,
        first_release_year=enrichment["first_release_year"] if enrichment else None,
    )


@router.put("/tracks/{track_id}", response_model=TrackDetail)
async def update_track(
    track_id: int,
    body: TrackUpdate,
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM track WHERE id = $1", track_id)
    if not existing:
        raise HTTPException(404, "Track not found")

    async with conn.transaction():
        updates = []
        params: list = []
        idx = 1

        if body.title is not None:
            updates.append(f"title = ${idx}")
            params.append(body.title)
            idx += 1
            updates.append(f"title_lower = ${idx}")
            params.append(body.title.lower())
            idx += 1

        if body.album_title is not None:
            updates.append(f"album_title = ${idx}")
            params.append(body.album_title or None)
            idx += 1

        if body.length_secs is not None:
            updates.append(f"length_secs = ${idx}")
            params.append(body.length_secs)
            idx += 1

        if updates:
            params.append(track_id)
            await conn.execute(
                f"UPDATE track SET {', '.join(updates)} WHERE id = ${idx}",
                *params,
            )

        if body.artists is not None:
            await conn.execute("DELETE FROM track_artist WHERE track_id = $1", track_id)
            for name in body.artists:
                name = name.strip()
                if not name:
                    continue
                aid = await conn.fetchval(
                    """INSERT INTO artist (name, name_lower)
                       VALUES ($1, $2)
                       ON CONFLICT (name_lower) DO UPDATE SET name = EXCLUDED.name
                       RETURNING id""",
                    name, name.lower(),
                )
                await conn.execute(
                    "INSERT INTO track_artist (track_id, artist_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    track_id, aid,
                )

    return await get_track(track_id, conn)


@router.delete("/tracks/{track_id}")
async def delete_track(
    track_id: int,
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM track WHERE id = $1", track_id)
    if not existing:
        raise HTTPException(404, "Track not found")

    async with conn.transaction():
        await conn.execute("DELETE FROM scrobble WHERE track_id = $1", track_id)
        await conn.execute("DELETE FROM music_scrobble_link WHERE track_id = $1", track_id)
        await conn.execute("DELETE FROM track_artist WHERE track_id = $1", track_id)
        await conn.execute("DELETE FROM track WHERE id = $1", track_id)

    return {"status": "deleted"}


@router.get("/tracks/{track_id}/scrobbles", response_model=ScrobbleList)
async def track_scrobbles(
    track_id: int,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM track WHERE id = $1", track_id)
    if not existing:
        raise HTTPException(404, "Track not found")

    total = await conn.fetchval(
        "SELECT count(*) FROM scrobble WHERE track_id = $1", track_id
    )

    rows = await conn.fetch("""
        SELECT s.id, s.listened_at, s.track_id, s.duration,
               t.title AS track_title, t.album_title,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) AS artist_names
        FROM scrobble s
        JOIN track t ON t.id = s.track_id
        LEFT JOIN track_artist ta ON ta.track_id = t.id
        LEFT JOIN artist a ON a.id = ta.artist_id
        WHERE s.track_id = $1
        GROUP BY s.id, t.id
        ORDER BY s.listened_at DESC
        LIMIT $2 OFFSET $3
    """, track_id, limit + 1, offset)

    has_more = len(rows) > limit
    items = [
        ScrobbleItem(
            id=r["id"],
            listened_at=r["listened_at"].isoformat(),
            track_id=r["track_id"],
            track_title=r["track_title"],
            artist_names=r["artist_names"] or [],
            album_title=r["album_title"],
            duration=r["duration"],
        )
        for r in rows[:limit]
    ]
    return ScrobbleList(items=items, total=total, has_more=has_more)
