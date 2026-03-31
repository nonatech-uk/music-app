"""Maloja-compatible scrobble receiver that writes directly to PostgreSQL."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import re

import asyncpg
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send


class SlashNormalizationMiddleware:
    """Collapse duplicate slashes in URL paths."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            scope["path"] = re.sub(r"/+", "/", scope["path"])
        await self.app(scope, receive, send)

API_KEY = os.environ.get("MALOJA_API_KEY", "")
pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app):
    global pool
    pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "scrobble"),
        password=os.environ["POSTGRES_PASSWORD"],
        database="scrobble",
        min_size=1,
        max_size=3,
    )
    yield
    if pool:
        await pool.close()


def _check_key(key: str | None) -> JSONResponse | None:
    if not API_KEY or key != API_KEY:
        return JSONResponse({"status": "error", "error": "invalid key"}, status_code=403)
    return None


async def serverinfo(request: Request) -> JSONResponse:
    """GET /apis/mlj_1/serverinfo — multi-scrobbler checks version and health on init."""
    return JSONResponse({
        "name": "music-app",
        "version": ["3", "2", "4"],
        "versionstring": "3.2.4",
        "db_status": {"healthy": True, "rebuildinprogress": False, "complete": True},
    })


async def scrobbles(request: Request) -> JSONResponse:
    """GET /apis/mlj_1/scrobbles — return recent scrobbles for dedup."""
    return JSONResponse({"list": []})


async def test(request: Request) -> JSONResponse:
    """GET /apis/mlj_1/test — multi-scrobbler calls this on startup."""
    err = _check_key(request.query_params.get("key"))
    if err:
        return err
    return JSONResponse({"status": "ok"})


async def newscrobble(request: Request) -> JSONResponse:
    """POST /apis/mlj_1/newscrobble — accept a scrobble and write to PostgreSQL."""
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

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Upsert artists
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

            # Upsert track
            track_id = await conn.fetchval(
                """INSERT INTO track (title, title_lower, album_title, length_secs)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (title_lower, album_title) DO UPDATE SET title = EXCLUDED.title
                   RETURNING id""",
                title, title.lower(), album, length,
            )

            # Track-artist links
            for aid in artist_ids.values():
                await conn.execute(
                    """INSERT INTO track_artist (track_id, artist_id)
                       VALUES ($1, $2)
                       ON CONFLICT DO NOTHING""",
                    track_id, aid,
                )

            # Insert scrobble
            await conn.execute(
                """INSERT INTO scrobble (listened_at, track_id, duration, origin)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT DO NOTHING""",
                listened_at, track_id, duration, "multi-scrobbler",
            )

    return JSONResponse({"status": "success", "track": {"artists": artists, "title": title}})


async def health(request: Request) -> JSONResponse:
    """GET /health — container health check."""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)


app = Starlette(
    middleware=[Middleware(SlashNormalizationMiddleware)],
    routes=[
        Route("/apis/mlj_1/serverinfo", serverinfo),
        Route("/apis/mlj_1/scrobbles", scrobbles),
        Route("/apis/mlj_1/test", test),
        Route("/apis/mlj_1/newscrobble", newscrobble, methods=["POST"]),
        Route("/health", health),
    ],
    lifespan=lifespan,
)


def main():
    uvicorn.run(app, host="0.0.0.0", port=42010, log_level="info")


if __name__ == "__main__":
    main()
