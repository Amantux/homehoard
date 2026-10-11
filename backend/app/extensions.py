"""Shared extension instances."""
import hashlib
import sqlite3

from flask import request
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

# Rate limiter — keyed on the caller's identity, not just the address: behind
# Home Assistant ingress every household member shares one peer IP, so a pure
# per-IP bucket lets one person lock everyone else out (see PROXY_HOPS / the
# `proxy_hops` add-on option for X-Forwarded-For handling). Sensitive endpoints
# opt in via @limiter.limit(...).
# No RATELIMIT_STORAGE_URI is set, so counters live in memory PER GUNICORN
# WORKER: with `-w 2` (docker-entrypoint.sh) a client's effective limit is ×2.
# The add-on ships no redis, so this is accepted rather than "fixed".
_LOGIN_PATH = "/users/login"
_REGISTER_PATH = "/users/register"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def _limiter_key() -> str:
    """Bucket key, evaluated by Flask-Limiter on every request.

    login: IP + submitted email, so guessing at one account does not throttle
    the others behind the same address. The Authorization header is
    deliberately NOT used there: it is unauthenticated input, and keying on it
    would let an attacker mint a fresh bucket per attempt. Register stays on
    the bare IP for the same reason, and because keying it on the submitted
    email would let one address mint unlimited accounts by varying the email.
    Elsewhere: the credential (hash of the Authorization header) when present,
    else the remote IP. Never raises."""
    ip = get_remote_address() or "unknown"
    try:
        if request.path.endswith(_LOGIN_PATH):
            data = request.get_json(silent=True)
            ident = None
            if isinstance(data, dict):
                ident = data.get("username") or data.get("email")
            if not ident:
                ident = request.form.get("username")
            if isinstance(ident, str) and ident.strip():
                return f"ip+email:{ip}:{_digest(ident.strip().lower())}"
            return ip
        if request.path.endswith(_REGISTER_PATH):
            return ip
        auth = request.headers.get("Authorization")
        if auth:
            return "cred:" + _digest(auth)
    except Exception:  # noqa: BLE001 - a key function must never break a request
        pass
    return ip


limiter = Limiter(key_func=_limiter_key, default_limits=[])
