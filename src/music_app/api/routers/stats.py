"""Overview statistics endpoint."""

from fastapi import APIRouter, Depends

import asyncpg

from music_app.api.deps import get_conn

router = APIRouter()


@router.get("/stats/overview")
async def overview(conn: asyncpg.Connection = Depends(get_conn)):
    total_tracks = await conn.fetchval("SELECT count(*) FROM track")
    total_artists = await conn.fetchval("SELECT count(*) FROM artist")
    scrobbles_today = await conn.fetchval(
        "SELECT count(*) FROM scrobble WHERE listened_at::date = CURRENT_DATE"
    )
    top_row = await conn.fetchrow("""
        SELECT a.name
        FROM scrobble s
        JOIN track_artist ta ON ta.track_id = s.track_id
        JOIN artist a ON a.id = ta.artist_id
        WHERE s.listened_at >= now() - interval '7 days'
        GROUP BY a.name
        ORDER BY count(*) DESC
        LIMIT 1
    """)

    return {
        "total_tracks": total_tracks,
        "total_artists": total_artists,
        "scrobbles_today": scrobbles_today,
        "top_artist": top_row["name"] if top_row else None,
    }
