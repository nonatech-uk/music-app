"""Connection pool, auth dependencies."""

from psycopg2.extras import RealDictCursor

from mees_shared.db import get_conn, init_pool as _init_pool, close_pool  # noqa: F401
from mees_shared.auth import CurrentUser, get_current_user as _make_get_user  # noqa: F401
import mees_shared.db as _db_mod

from config.settings import settings

# App-specific auth dependency
get_current_user = _make_get_user(settings.auth_enabled, settings.dev_user_email)

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    email TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin'
);
INSERT INTO app_user (email, display_name, role)
VALUES ('stu@mees.st', 'Stu', 'admin')
ON CONFLICT DO NOTHING;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""


def init_pool() -> None:
    _init_pool(settings.dsn, settings.db_pool_min, settings.db_pool_max)
    conn = _db_mod.pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
    finally:
        _db_mod.pool.putconn(conn)


def dict_cursor(conn):
    """Return a RealDictCursor for dict-like row access (matches old asyncpg behaviour)."""
    return conn.cursor(cursor_factory=RealDictCursor)
