"""Recent scrobbles endpoint."""

from fastapi import APIRouter, Depends, Query

import asyncpg

from music_app.api.deps import get_conn
from music_app.api.models import ScrobbleItem, ScrobbleList

router = APIRouter()


@router.get("/scrobbles", response_model=ScrobbleList)
async def list_scrobbles(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await conn.fetchval("SELECT count(*) FROM scrobble")

    rows = await conn.fetch("""
        SELECT s.id, s.listened_at, s.track_id, s.duration,
               t.title AS track_title, t.album_title,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) AS artist_names
        FROM scrobble s
        JOIN track t ON t.id = s.track_id
        LEFT JOIN track_artist ta ON ta.track_id = t.id
        LEFT JOIN artist a ON a.id = ta.artist_id
        GROUP BY s.id, t.id
        ORDER BY s.listened_at DESC
        LIMIT $1 OFFSET $2
    """, limit + 1, offset)

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
