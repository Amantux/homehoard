"""Legacy configuration shim.

Every setting is declared once, in the ``app.settings`` registry, and resolved
by ``load_settings()`` (override → HA option → env → default); ``create_app``
puts ``settings.values`` into ``app.config``. This class no longer reads
``os.environ`` itself — it used to, at import time, which made it a second
source of truth: a ``Config`` subclass inherited that import-time snapshot for
every field, and ``_settings_from`` turned each inherited value into an
explicit override.

What remains:
- ``create_app(Config)`` (the bare class) means "resolve normally".
- A subclass (tests, one-off apps) sets only the attributes it wants to pin;
  each attribute named like a registry Field becomes an explicit override,
  everything else resolves through ``load_settings``.
- ``sqlalchemy_uri()`` / ``_normalize_db_url()`` and the ``ensure_secret_key``
  re-export, which callers still import from here.
"""


class Config:
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
