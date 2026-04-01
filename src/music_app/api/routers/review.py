"""Review endpoints for music library cleanup and MusicBrainz hygiene."""

from fastapi import APIRouter, Depends, HTTPException, Query

import asyncpg

from music_app.api.deps import get_conn
from music_app.api.models import (
    DuplicateCandidate,
    DuplicateList,
    LinkUpdate,
    MergeRequest,
    ReviewItem,
    ReviewList,
    ReviewStats,
)

router = APIRouter()


@router.get("/review/stats", response_model=ReviewStats)
async def review_stats(conn: asyncpg.Connection = Depends(get_conn)):
    row = await conn.fetchrow("""
        SELECT
            (SELECT COUNT(DISTINCT artist_string) FROM music_scrobble_link) AS total_artists,
            (SELECT COUNT(DISTINCT artist_string) FROM music_scrobble_link WHERE artist_mbid IS NOT NULL) AS resolved_artists,
            (SELECT COUNT(*) FROM music_scrobble_link) AS total_recordings,
            (SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL) AS resolved_recordings,
            (SELECT COUNT(*) FROM scrobble) AS total_scrobbles,
            (SELECT COUNT(DISTINCT s.id) FROM scrobble s
             JOIN track t ON t.id = s.track_id
             JOIN track_artist ta ON ta.track_id = t.id
             JOIN artist a ON a.id = ta.artist_id
             JOIN music_scrobble_link sl ON sl.artist_string = a.name_lower AND sl.track_string = t.title_lower
             WHERE sl.recording_mbid IS NOT NULL) AS linked_scrobbles,
            (SELECT COUNT(*) FROM music_scrobble_link WHERE resolution_method = 'failed') AS failed_count,
            (SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL AND resolution_score >= 0.99) AS confidence_99_plus,
            (SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL AND resolution_score >= 0.95 AND resolution_score < 0.99) AS confidence_95_99,
            (SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL AND resolution_score >= 0.90 AND resolution_score < 0.95) AS confidence_90_95
    """)
    return ReviewStats(**dict(row))


def _row_to_review_item(row: asyncpg.Record) -> ReviewItem:
    return ReviewItem(
        link_id=row["link_id"],
        artist_id=row.get("artist_id"),
        track_id=row.get("track_id"),
        artist_string=row["artist_string"],
        track_string=row["track_string"],
        scrobble_count=row["scrobble_count"],
        last_played=row["last_played"].isoformat() if row.get("last_played") else None,
        resolution_method=row.get("resolution_method"),
        resolution_score=row.get("resolution_score"),
        matched_artist=row.get("matched_artist"),
        matched_recording=row.get("matched_recording"),
        artist_mbid=str(row["artist_mbid"]) if row.get("artist_mbid") else None,
        recording_mbid=str(row["recording_mbid"]) if row.get("recording_mbid") else None,
        reviewed_at=row["reviewed_at"].isoformat() if row.get("reviewed_at") else None,
    )


@router.get("/review/unresolved", response_model=ReviewList)
async def list_unresolved(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NULL AND resolution_method IS DISTINCT FROM 'failed'"
    )
    rows = await conn.fetch("""
        SELECT sl.id AS link_id, sl.artist_id, sl.track_id,
               sl.artist_string, sl.track_string,
               sl.resolution_method, sl.resolution_score,
               sl.artist_mbid, sl.recording_mbid, sl.reviewed_at,
               ma.name AS matched_artist, NULL AS matched_recording,
               COUNT(s.id) AS scrobble_count, MAX(s.listened_at) AS last_played
        FROM music_scrobble_link sl
        LEFT JOIN music_artist ma ON ma.mbid = sl.artist_mbid
        LEFT JOIN scrobble s ON s.track_id = sl.track_id
        WHERE sl.recording_mbid IS NULL
          AND sl.resolution_method IS DISTINCT FROM 'failed'
        GROUP BY sl.id, ma.name
        ORDER BY scrobble_count DESC
        LIMIT $1 OFFSET $2
    """, limit + 1, offset)

    has_more = len(rows) > limit
    items = [_row_to_review_item(r) for r in rows[:limit]]
    return ReviewList(items=items, total=total, has_more=has_more)


@router.get("/review/failed", response_model=ReviewList)
async def list_failed(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM music_scrobble_link WHERE resolution_method = 'failed'"
    )
    rows = await conn.fetch("""
        SELECT sl.id AS link_id, sl.artist_id, sl.track_id,
               sl.artist_string, sl.track_string,
               sl.resolution_method, sl.resolution_score,
               sl.artist_mbid, sl.recording_mbid, sl.reviewed_at,
               NULL AS matched_artist, NULL AS matched_recording,
               COUNT(s.id) AS scrobble_count, MAX(s.listened_at) AS last_played
        FROM music_scrobble_link sl
        LEFT JOIN scrobble s ON s.track_id = sl.track_id
        WHERE sl.resolution_method = 'failed'
        GROUP BY sl.id
        ORDER BY scrobble_count DESC
        LIMIT $1 OFFSET $2
    """, limit + 1, offset)

    has_more = len(rows) > limit
    items = [_row_to_review_item(r) for r in rows[:limit]]
    return ReviewList(items=items, total=total, has_more=has_more)


@router.get("/review/low-confidence", response_model=ReviewList)
async def list_low_confidence(
    threshold: float = Query(0.95),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL AND resolution_score < $1 AND reviewed_at IS NULL",
        threshold,
    )
    rows = await conn.fetch("""
        SELECT sl.id AS link_id, sl.artist_id, sl.track_id,
               sl.artist_string, sl.track_string,
               sl.resolution_method, sl.resolution_score,
               sl.artist_mbid, sl.recording_mbid, sl.reviewed_at,
               ma.name AS matched_artist, mr.title AS matched_recording,
               COUNT(s.id) AS scrobble_count, MAX(s.listened_at) AS last_played
        FROM music_scrobble_link sl
        LEFT JOIN music_artist ma ON ma.mbid = sl.artist_mbid
        LEFT JOIN music_recording mr ON mr.mbid = sl.recording_mbid
        LEFT JOIN scrobble s ON s.track_id = sl.track_id
        WHERE sl.recording_mbid IS NOT NULL
          AND sl.resolution_score < $1
          AND sl.reviewed_at IS NULL
        GROUP BY sl.id, ma.name, mr.title
        ORDER BY sl.resolution_score ASC
        LIMIT $2 OFFSET $3
    """, threshold, limit + 1, offset)

    has_more = len(rows) > limit
    items = [_row_to_review_item(r) for r in rows[:limit]]
    return ReviewList(items=items, total=total, has_more=has_more)


@router.put("/review/link/{link_id}")
async def update_link(
    link_id: int,
    body: LinkUpdate,
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM music_scrobble_link WHERE id = $1", link_id)
    if not existing:
        raise HTTPException(404, "Link not found")

    async with conn.transaction():
        updates = ["reviewed_at = now()", "manual_override = true"]
        params: list = []
        idx = 1

        if body.artist_mbid is not None:
            updates.append(f"artist_mbid = ${idx}::uuid")
            params.append(body.artist_mbid)
            idx += 1

        if body.recording_mbid is not None:
            updates.append(f"recording_mbid = ${idx}::uuid")
            params.append(body.recording_mbid)
            idx += 1
            updates.append("resolution_method = 'manual'")

        params.append(link_id)
        await conn.execute(
            f"UPDATE music_scrobble_link SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )

    return {"status": "updated"}


@router.post("/review/confirm/{link_id}")
async def confirm_link(
    link_id: int,
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM music_scrobble_link WHERE id = $1", link_id)
    if not existing:
        raise HTTPException(404, "Link not found")

    await conn.execute(
        "UPDATE music_scrobble_link SET reviewed_at = now() WHERE id = $1",
        link_id,
    )
    return {"status": "confirmed"}


@router.post("/review/reject/{link_id}")
async def reject_link(
    link_id: int,
    conn: asyncpg.Connection = Depends(get_conn),
):
    existing = await conn.fetchrow("SELECT id FROM music_scrobble_link WHERE id = $1", link_id)
    if not existing:
        raise HTTPException(404, "Link not found")

    await conn.execute("""
        UPDATE music_scrobble_link
        SET recording_mbid = NULL, artist_mbid = NULL,
            resolution_method = 'rejected', reviewed_at = now(), manual_override = true
        WHERE id = $1
    """, link_id)
    return {"status": "rejected"}


@router.get("/review/duplicates", response_model=DuplicateList)
async def list_duplicates(
    type: str = Query("artist"),
    threshold: float = Query(0.7),
    limit: int = Query(50, le=100),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Ensure pg_trgm extension exists
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    if type == "artist":
        rows = await conn.fetch("""
            SELECT a1.id AS id_a, a1.name AS name_a,
                   (SELECT COUNT(*) FROM track_artist WHERE artist_id = a1.id) AS count_a,
                   a2.id AS id_b, a2.name AS name_b,
                   (SELECT COUNT(*) FROM track_artist WHERE artist_id = a2.id) AS count_b,
                   similarity(a1.name_lower, a2.name_lower) AS similarity
            FROM artist a1
            JOIN artist a2 ON a1.id < a2.id
                AND similarity(a1.name_lower, a2.name_lower) > $1
            ORDER BY similarity DESC
            LIMIT $2
        """, threshold, limit)
    else:
        return DuplicateList(items=[])

    items = [
        DuplicateCandidate(
            id_a=r["id_a"], name_a=r["name_a"], count_a=r["count_a"],
            id_b=r["id_b"], name_b=r["name_b"], count_b=r["count_b"],
            similarity=round(r["similarity"], 3),
        )
        for r in rows
    ]
    return DuplicateList(items=items)


@router.post("/review/merge")
async def merge_artists(
    body: MergeRequest,
    conn: asyncpg.Connection = Depends(get_conn),
):
    keep = await conn.fetchrow("SELECT id, name FROM artist WHERE id = $1", body.keep_id)
    remove = await conn.fetchrow("SELECT id, name FROM artist WHERE id = $1", body.remove_id)
    if not keep or not remove:
        raise HTTPException(404, "Artist not found")

    async with conn.transaction():
        # Reassign track_artist links
        await conn.execute("""
            UPDATE track_artist SET artist_id = $1
            WHERE artist_id = $2
              AND track_id NOT IN (SELECT track_id FROM track_artist WHERE artist_id = $1)
        """, body.keep_id, body.remove_id)
        # Remove remaining duplicates
        await conn.execute("DELETE FROM track_artist WHERE artist_id = $1", body.remove_id)
        # Update scrobble links
        await conn.execute(
            "UPDATE music_scrobble_link SET artist_id = $1 WHERE artist_id = $2",
            body.keep_id, body.remove_id,
        )
        # Delete the merged artist
        await conn.execute("DELETE FROM artist WHERE id = $1", body.remove_id)

    return {"status": "merged", "kept": keep["name"], "removed": remove["name"]}
