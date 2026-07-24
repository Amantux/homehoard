"""Application configuration.

HomeHoard is a Python (Flask) port of homebox. Configuration is driven by
environment variables so it can run standalone or as a Home Assistant add-on.
"""
import os
from datetime import timedelta


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # --- Storage ---------------------------------------------------------
    DATA_DIR = os.environ.get("HBOX_DATA_DIR", os.path.abspath("./data"))
    DATABASE_URL = os.environ.get("HBOX_DATABASE_URL")

    # --- Security --------------------------------------------------------
    SECRET_KEY = os.environ.get("HBOX_SECRET_KEY", "change-me-in-production")
    JWT_EXPIRES = timedelta(hours=int(os.environ.get("HBOX_JWT_HOURS", "72")))

    # Ship-defaults that must never sign real tokens. The app fails closed when
    # one of these is in use with auth enabled (see create_app).
    KNOWN_DEFAULT_SECRETS = frozenset({
        "change-me-in-production",
        "please-change-me-to-a-long-random-string",
    })

    # When auth is disabled the app runs single-tenant against a default
    # user/group. Intended for deployment behind Home Assistant ingress,
    # which already enforces authentication.
    DISABLE_AUTH = _bool("HBOX_DISABLE_AUTH", False)

    # Allow public self-registration of new users/groups.
    ALLOW_REGISTRATION = _bool("HBOX_ALLOW_REGISTRATION", True)

    # Minimum password length enforced on register / change-password.
    MIN_PASSWORD_LENGTH = int(os.environ.get("HBOX_MIN_PASSWORD_LENGTH", "8"))

    # --- Network / proxy -------------------------------------------------
    # Explicit CORS origin allowlist (comma-separated). Empty => same-origin
    # only (the SPA is served from the same origin, so no CORS is needed).
    CORS_ORIGINS = [
        o.strip() for o in os.environ.get("HBOX_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    # Number of trusted reverse proxies in front of the app, so the real client
    # IP (X-Forwarded-For) drives rate limiting instead of the proxy's IP.
    # Default 0 = trust nothing: a direct-exposed app must NOT honor a spoofable
    # X-Forwarded-For. Operators behind a real proxy set this to the hop count.
    PROXY_HOPS = int(os.environ.get("HBOX_PROXY_HOPS", "0"))
    # Enable request rate limiting (disabled automatically under tests).
    RATELIMIT_ENABLED = _bool("HBOX_RATELIMIT_ENABLED", True)

    # --- Misc ------------------------------------------------------------
    MAX_UPLOAD_BYTES = int(os.environ.get("HBOX_MAX_UPLOAD_MB", "50")) * 1024 * 1024
    JSON_SORT_KEYS = False

    @staticmethod
    def _normalize_db_url(url: str) -> str:
        """Pin the psycopg (v3) driver for Postgres URLs. `postgres://` (Heroku
        style) and bare `postgresql://` both resolve to psycopg2 in SQLAlchemy,
        which we don't ship — rewrite them to `postgresql+psycopg://`."""
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @classmethod
    def sqlalchemy_uri(cls) -> str:
        raw = (cls.DATABASE_URL or "").strip()
        if raw:  # a blank / whitespace-only value falls through to SQLite
            url = cls._normalize_db_url(raw)
            scheme = url.split(":", 1)[0]
            if not (scheme.startswith("sqlite") or scheme.startswith("postgresql")):
                raise RuntimeError(
                    f"HBOX_DATABASE_URL scheme {scheme!r} is unsupported. Only SQLite "
                    "(default) and Postgres (postgresql+psycopg://user:pass@host/db) "
                    "are supported."
                )
            if scheme.startswith("postgresql+") and scheme != "postgresql+psycopg":
                raise RuntimeError(
                    f"HBOX_DATABASE_URL driver {scheme!r} isn't bundled — use "
                    "postgresql+psycopg:// (the sync psycopg 3 driver HomeHoard ships)."
                )
            return url
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        return f"sqlite:///{os.path.join(cls.DATA_DIR, 'homehoard.db')}"

    @classmethod
    def attachments_dir(cls) -> str:
        path = os.path.join(cls.DATA_DIR, "attachments")
        os.makedirs(path, exist_ok=True)
        return path
