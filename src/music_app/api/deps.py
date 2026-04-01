"""Shared dependencies: asyncpg pool and connection injection."""

import os
from collections.abc import AsyncGenerator

import asyncpg

pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global pool
    pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "scrobble"),
        password=os.environ["POSTGRES_PASSWORD"],
        database="scrobble",
        min_size=1,
        max_size=5,
    )


async def close_pool() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None


async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    assert pool is not None, "Connection pool not initialised"
    async with pool.acquire() as conn:
        yield conn
