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
    # One-shot: when DATABASE_URL points at an EMPTY Postgres and a local SQLite DB
    # exists, copy the SQLite data into Postgres on startup before serving.
    MIGRATE_FROM_SQLITE = _bool("HBOX_MIGRATE_FROM_SQLITE", False)
    # Auto-provision a private database on the shared "Shared PostgreSQL" add-on
    # (opt-in). When on and no explicit DATABASE_URL is set, `app.pg_provision`
    # discovers the add-on at startup and writes the resulting DSN to
    # <DATA_DIR>/.database_url, which sqlalchemy_uri() then reads. Blank token =
    # auto-obtained from the add-on's Supervisor discovery message.
    USE_SHARED_POSTGRES = _bool("HBOX_USE_SHARED_POSTGRES", False)
    POSTGRES_PROVISION_TOKEN = os.environ.get("HBOX_POSTGRES_PROVISION_TOKEN", "")

    # --- AI provider (chat + tooling) ------------------------------------
    # HomeHoard talks to LLMs through a provider-agnostic layer (services/ai).
    # Pick the backend here or in Tools → AI provider (the UI override wins).
    # "ollama" (local/self-hosted), "openai" (any OpenAI-compatible server, incl.
    # local SLMs via a base URL), or "claude" (hosted Anthropic). Blank = off.
    AI_PROVIDER = os.environ.get("HBOX_AI_PROVIDER", "")
    AI_TIMEOUT_SECONDS = int(os.environ.get("HBOX_AI_TIMEOUT_SECONDS", "60"))
    # Auto-categorization: a proposed label at/above this model-reported confidence
    # (and matching an existing label) is applied automatically; below it, or a new
    # label, goes to the review queue. 0..1.
    AI_CONFIDENCE_THRESHOLD = float(os.environ.get("HBOX_AI_CONFIDENCE_THRESHOLD", "0.8"))
    ANTHROPIC_API_KEY = os.environ.get("HBOX_ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL = os.environ.get("HBOX_CLAUDE_MODEL", "claude-opus-4-8")
    OPENAI_API_KEY = os.environ.get("HBOX_OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("HBOX_OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL = os.environ.get("HBOX_OPENAI_BASE_URL", "")

    # --- AI item enrichment (Ollama web search) --------------------------
    # Look items up online to generate a short searchable description. The search
    # key is the hosted Ollama API key (ollama.com); the configured AI provider
    # synthesizes the result. Blank key = enrichment is simply off.
    OLLAMA_SEARCH_KEY = os.environ.get("HBOX_OLLAMA_SEARCH_KEY", "")
    OLLAMA_URL = os.environ.get("HBOX_OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.environ.get("HBOX_OLLAMA_MODEL", "llama3.1")
    # Ollama Cloud (ollama.com) — a distinct provider; the host is pinned, so only
    # its own key + model are configurable (kept separate from a local Ollama).
    OLLAMA_CLOUD_API_KEY = os.environ.get("HBOX_OLLAMA_CLOUD_API_KEY", "")
    OLLAMA_CLOUD_MODEL = os.environ.get("HBOX_OLLAMA_CLOUD_MODEL", "")

    # --- Barcode identification (scan a UPC/EAN → identify the product) ---
    # Off by default (network). A product barcode DB (UPCitemdb trial by default —
    # no key) with an Open Food Facts + Ollama web-search fallback.
    BARCODE_LOOKUP = _bool("HBOX_BARCODE_LOOKUP", False)
    BARCODE_DB_URL = os.environ.get(
        "HBOX_BARCODE_DB_URL", "https://api.upcitemdb.com/prod/trial/lookup")
    BARCODE_DB_KEY = os.environ.get("HBOX_BARCODE_DB_KEY", "")

    # --- Security --------------------------------------------------------
    # Blank means "not supplied" — create_app then reads (or generates once and
    # persists) a key under DATA_DIR. It is deliberately NOT defaulted to a
    # placeholder here: a placeholder that reached this attribute could not be
    # told apart from an operator explicitly setting one, which must fail closed.
    SECRET_KEY = os.environ.get("HBOX_SECRET_KEY", "")
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

    # Background job worker (async AI tooling). On by default; disabled in tests,
    # which drive the job functions directly.
    WORKER_ENABLED = _bool("HBOX_WORKER_ENABLED", True)

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

    # --- delegation to the configuration registry -------------------------
    # These used to hold a SECOND implementation of DB-URL normalization and
    # SQLite fallback. They now forward to app.settings so there is exactly one,
    # per the one-adapter rule. Kept as classmethods because migrations/env.py
    # and services/db_copy call them by name.

    @staticmethod
    def _normalize_db_url(url: str) -> str:
        from .settings import normalize_db_scheme
        return normalize_db_scheme(url)

    @classmethod
    def sqlalchemy_uri(cls) -> str:
        """Resolve the database URL, honouring attributes set on a subclass.

        Subclassing Config to override DATABASE_URL/DATA_DIR is the established
        way callers (and tests) express a one-off configuration, so those
        attributes become explicit overrides. Called on the bare Config it means
        "resolve normally", which includes /data/options.json.
        """
        from .settings import FIELDS_BY_NAME, load_settings
        # validate=False: this answers "which database?" for the bare `alembic`
        # CLI (migrations/env.py), a recovery path that must not abort because
        # an unrelated setting like CORS_ORIGINS is wrong.
        if cls is Config:
            return load_settings(validate=False).sqlalchemy_uri
        overrides = {n: getattr(cls, n) for n in FIELDS_BY_NAME if hasattr(cls, n)}
        return load_settings(overrides=overrides, ha_options={},
                             validate=False).sqlalchemy_uri


# Moved to app/settings.py (one place for secret handling); re-exported so
# `from app.config import ensure_secret_key` keeps resolving.
from .settings import ensure_secret_key  # noqa: E402,F401
