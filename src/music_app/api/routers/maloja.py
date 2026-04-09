"""Maloja-compatible API endpoints for multi-scrobbler."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config.settings import settings
from music_app.api.deps import dict_cursor, get_conn

router = APIRouter()


def _check_key(key: str | None) -> JSONResponse | None:
    if not settings.maloja_api_key or key != settings.maloja_api_key:
        return JSONResponse({"status": "error", "error": "invalid key"}, status_code=403)
    return None


@router.get("/serverinfo")
def serverinfo():
    return {
        "name": "music-app",
        "version": ["3", "2", "4"],
        "versionstring": "3.2.4",
        "db_status": {"healthy": True, "rebuildinprogress": False, "complete": True},
    }


@router.get("/scrobbles")
def scrobbles():
    return {"list": []}


@router.get("/test")
def test(request: Request):
    err = _check_key(request.query_params.get("key"))
    if err:
        return err
    return {"status": "ok"}


@router.post("/newscrobble")
async def newscrobble(request: Request, conn=Depends(get_conn)):
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

    cur = dict_cursor(conn)

    artist_ids: dict[str, int] = {}
    for name in artists:
        name = name.strip()
        if not name:
            continue
        cur.execute(
            """INSERT INTO artist (name, name_lower)
               VALUES (%s, %s)
               ON CONFLICT (name_lower) DO UPDATE SET name = EXCLUDED.name
               RETURNING id""",
            (name, name.lower()),
        )
        artist_ids[name] = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO track (title, title_lower, album_title, length_secs)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (title_lower, album_title) DO UPDATE SET title = EXCLUDED.title
           RETURNING id""",
        (title, title.lower(), album, length),
    )
    track_id = cur.fetchone()["id"]

    for aid in artist_ids.values():
        cur.execute(
            """INSERT INTO track_artist (track_id, artist_id)
               VALUES (%s, %s)
               ON CONFLICT DO NOTHING""",
            (track_id, aid),
        )

    cur.execute(
        """INSERT INTO scrobble (listened_at, track_id, duration, origin)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (listened_at, track_id, duration, "multi-scrobbler"),
    )
    conn.commit()

    return {"status": "success", "track": {"artists": artists, "title": title}}
