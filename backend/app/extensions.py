"""Shared extension instances."""
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """Durability/concurrency hardening for the embedded SQLite database:
    - WAL: readers don't block the writer (the API + MCP process share the DB).
    - busy_timeout: a contended write waits up to 5s instead of failing instantly.
    - foreign_keys: enforce referential integrity (off by default in SQLite).
    No-op for any non-SQLite backend."""
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

# Rate limiter — keyed on the client IP (see PROXY_HOPS for X-Forwarded-For
# handling). Sensitive endpoints opt in via @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address, default_limits=[])
