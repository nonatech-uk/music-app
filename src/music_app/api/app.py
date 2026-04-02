"""FastAPI application: mounts Maloja-compat API, new REST API, and SPA."""

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from music_app.api.deps import close_pool, init_pool
from music_app.api.routers import artists, maloja, review, scrobbles, stats, tracks

STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parent.parent.parent.parent / "static"))


class SlashNormalizationMiddleware:
    """Collapse duplicate slashes in URL paths."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            scope["path"] = re.sub(r"/+", "/", scope["path"])
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Music App", version="0.1.0", lifespan=lifespan)

app.add_middleware(SlashNormalizationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://music.mees.st", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Maloja-compat endpoints (used by multi-scrobbler)
app.include_router(maloja.router, prefix="/apis/mlj_1")

# New REST API
app.include_router(tracks.router, prefix="/api/v1", tags=["tracks"])
app.include_router(artists.router, prefix="/api/v1", tags=["artists"])
app.include_router(scrobbles.router, prefix="/api/v1", tags=["scrobbles"])
app.include_router(review.router, prefix="/api/v1", tags=["review"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])


@app.get("/health")
async def health():
    from music_app.api.deps import pool

    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)


# SPA static file serving
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file_path = STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
