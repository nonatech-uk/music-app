"""Artist list and search endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

import asyncpg

from music_app.api.deps import get_conn
from music_app.api.models import ArtistDetail, ArtistItem, ArtistList, TrackItem

router = APIRouter()


@router.get("/artists", response_model=ArtistList)
async def list_artists(
    q: str | None = Query(None),
    sort: str = Query("name"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    conditions = []
    params: list = []
    idx = 1

    if q:
        conditions.append(f"a.name_lower LIKE ${idx}")
        params.append(f"%{q.lower()}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    sort_map = {
        "name": "a.name",
        "scrobbles": "scrobble_count DESC",
    }
    order = sort_map.get(sort, "a.name")

    total = await conn.fetchval(f"SELECT count(*) FROM artist a {where}", *params)

    rows = await conn.fetch(f"""
        SELECT a.id, a.name,
               count(DISTINCT ta.track_id) AS track_count,
               count(DISTINCT s.id) AS scrobble_count
        FROM artist a
        LEFT JOIN track_artist ta ON ta.artist_id = a.id
        LEFT JOIN scrobble s ON s.track_id = ta.track_id
        {where}
        GROUP BY a.id
        ORDER BY {order}
        LIMIT ${idx} OFFSET ${idx + 1}
    """, *params, limit + 1, offset)

    has_more = len(rows) > limit
    items = [
        ArtistItem(
            id=r["id"],
            name=r["name"],
            track_count=r["track_count"],
            scrobble_count=r["scrobble_count"],
        )
        for r in rows[:limit]
    ]
    return ArtistList(items=items, total=total, has_more=has_more)


@router.get("/artists/{artist_id}", response_model=ArtistDetail)
async def get_artist(
    artist_id: int,
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("""
        SELECT a.id, a.name,
               count(DISTINCT ta.track_id) AS track_count,
               count(DISTINCT s.id) AS scrobble_count
        FROM artist a
        LEFT JOIN track_artist ta ON ta.artist_id = a.id
        LEFT JOIN scrobble s ON s.track_id = ta.track_id
        WHERE a.id = $1
        GROUP BY a.id
    """, artist_id)

    if not row:
        raise HTTPException(404, "Artist not found")

    tracks = await conn.fetch("""
        SELECT t.id, t.title, t.album_title, t.length_secs,
               array_agg(DISTINCT a2.name) FILTER (WHERE a2.name IS NOT NULL) AS artists,
               count(DISTINCT s.id) AS scrobble_count,
               max(s.listened_at) AS last_scrobbled
        FROM track t
        JOIN track_artist ta ON ta.track_id = t.id
        LEFT JOIN track_artist ta2 ON ta2.track_id = t.id
        LEFT JOIN artist a2 ON a2.id = ta2.artist_id
        LEFT JOIN scrobble s ON s.track_id = t.id
        WHERE ta.artist_id = $1
        GROUP BY t.id
        ORDER BY scrobble_count DESC
        LIMIT 100
    """, artist_id)

    return ArtistDetail(
        id=row["id"],
        name=row["name"],
        track_count=row["track_count"],
        scrobble_count=row["scrobble_count"],
        tracks=[
            TrackItem(
                id=t["id"],
                title=t["title"],
                album_title=t["album_title"],
                length_secs=t["length_secs"],
                artists=t["artists"] or [],
                scrobble_count=t["scrobble_count"],
                last_scrobbled=t["last_scrobbled"].isoformat() if t["last_scrobbled"] else None,
            )
            for t in tracks
        ],
    )
