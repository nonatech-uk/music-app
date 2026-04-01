"""Maloja-compatible API endpoints for multi-scrobbler."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from music_app.api import deps

router = APIRouter()

API_KEY = os.environ.get("MALOJA_API_KEY", "")


def _check_key(key: str | None) -> JSONResponse | None:
    if not API_KEY or key != API_KEY:
        return JSONResponse({"status": "error", "error": "invalid key"}, status_code=403)
    return None


@router.get("/serverinfo")
async def serverinfo():
    return {
        "name": "music-app",
        "version": ["3", "2", "4"],
        "versionstring": "3.2.4",
        "db_status": {"healthy": True, "rebuildinprogress": False, "complete": True},
    }


@router.get("/scrobbles")
async def scrobbles():
    return {"list": []}


@router.get("/test")
async def test(request: Request):
    err = _check_key(request.query_params.get("key"))
    if err:
        return err
    return {"status": "ok"}


@router.post("/newscrobble")
async def newscrobble(request: Request):
    body = await request.json()

    err = _check_key(body.get("key"))
    if err:
        return err

    title = body.get("title", "").strip()
    artists = body.get("artists") or []
    album = body.get("album") or None
    timestamp = body.get("time")
    length = body.get("length")
    duration = body.get("duration")

    if not title or not timestamp:
        return JSONResponse(
            {"status": "error", "error": "title and time are required"},
            status_code=400,
        )

    if album:
        album = album.strip() or None

    listened_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)

    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            artist_ids: dict[str, int] = {}
            for name in artists:
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
                artist_ids[name] = aid

            track_id = await conn.fetchval(
                """INSERT INTO track (title, title_lower, album_title, length_secs)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (title_lower, album_title) DO UPDATE SET title = EXCLUDED.title
                   RETURNING id""",
                title, title.lower(), album, length,
            )

            for aid in artist_ids.values():
                await conn.execute(
                    """INSERT INTO track_artist (track_id, artist_id)
                       VALUES ($1, $2)
                       ON CONFLICT DO NOTHING""",
                    track_id, aid,
                )

            await conn.execute(
                """INSERT INTO scrobble (listened_at, track_id, duration, origin)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT DO NOTHING""",
                listened_at, track_id, duration, "multi-scrobbler",
            )

    return {"status": "success", "track": {"artists": artists, "title": title}}
