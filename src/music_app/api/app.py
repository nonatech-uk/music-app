"""FastAPI application: mounts Maloja-compat API, new REST API, and SPA."""

import asyncio
import logging
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from config.settings import settings
from music_app.api.deps import close_pool, init_pool
from music_app.api.routers import artists, maloja, review, scrobbles, stats, tracks

from mees_shared.usage_tracker import init_usage_tracker, shutdown_usage_tracker, track_usage_middleware, usage_pageview_router
from mees_shared.dashboard import register_with_dashboard
from mees_shared.spa import mount_spa

STATIC_DIR = Path(_project_root) / "static"

_log = logging.getLogger(__name__)


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
    init_pool()
    init_usage_tracker("music", settings.usage_dsn)
    task = asyncio.create_task(register_with_dashboard(
        label="Music",
        href="https://music.mees.st",
        icon="\u266B",
        sort_order=5,
        registry_key=settings.dash_registry_key,
    ))
    yield
    task.cancel()
    shutdown_usage_tracker()
    close_pool()


app = FastAPI(title="Music App", version="0.1.0", lifespan=lifespan)

app.add_middleware(SlashNormalizationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(track_usage_middleware)

# Maloja-compat endpoints (used by multi-scrobbler)
app.include_router(maloja.router, prefix="/apis/mlj_1")

# New REST API
app.include_router(tracks.router, prefix="/api/v1", tags=["tracks"])
app.include_router(artists.router, prefix="/api/v1", tags=["artists"])
app.include_router(scrobbles.router, prefix="/api/v1", tags=["scrobbles"])
app.include_router(review.router, prefix="/api/v1", tags=["review"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])
app.include_router(usage_pageview_router, prefix="/api/v1")

# SPA serving + /health endpoint
mount_spa(app, STATIC_DIR)
