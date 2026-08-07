"""HomeHoard application factory.

A Python (Flask) port of homebox — the inventory & organization system for the
home user. Ships an optional-auth JSON API under ``/api/v1`` and serves the
built Vue SPA.
"""
import logging
import os
import re
import time
import uuid

from flask import Flask, current_app, g, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import safe_join

from .config import Config
from .extensions import db, limiter
from .logging_setup import configure as configure_logging, request_id_var
from .logsafe import scrub
from .settings import FIELDS_BY_NAME, PLACEHOLDER_SECRETS, ensure_secret_key, load_settings

_LOGGER = logging.getLogger("homehoard")

# Request ids appear in every log line for a request; keep them boring.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]+")


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _settings_from(config_object):
    """Build Settings, honouring a legacy config object as a bag of overrides.

    Tests (and any caller passing a Config subclass) fully specify their
    configuration, so every attribute matching a declared field becomes an
    explicit override — which is also what lets several differently-configured
    apps exist in one process. Passing the bare Config class means "resolve
    normally" (env + /data/options.json).
    """
    if config_object is None or config_object is Config:
        return load_settings()

    overrides = {}
    for name in FIELDS_BY_NAME:
        if hasattr(config_object, name):
            overrides[name] = getattr(config_object, name)
    # Legacy derived attributes: the old Config exposed the computed value, the
    # registry declares the input. Only fill in if the caller didn't set the
    # input directly.
    if hasattr(config_object, "MAX_UPLOAD_BYTES") and "MAX_UPLOAD_MB" not in overrides:
        overrides["MAX_UPLOAD_MB"] = max(1, int(config_object.MAX_UPLOAD_BYTES) // (1024 * 1024))
    if hasattr(config_object, "JWT_EXPIRES") and "JWT_HOURS" not in overrides:
        overrides["JWT_HOURS"] = max(1, int(config_object.JWT_EXPIRES.total_seconds() // 3600))
    return load_settings(overrides=overrides, ha_options={})


def create_app(config_object=Config):
    app = Flask(__name__, static_folder=None)
    settings = _settings_from(config_object)

    # Every declared field is exposed under its own name, exactly as
    # `from_object(Config)` used to expose the class attributes — so existing
    # `app.config["AI_PROVIDER"]`-style reads keep working.
    # Before anything else logs: until this release HomeHoard configured logging
    # nowhere, so every INFO line was discarded and the only handler present had
    # been installed as a side effect of Alembic's fileConfig.
    configure_logging(settings, process="app")

    app.config.update(settings.values)
    app.config["SETTINGS"] = settings
    # Absolute, matching the old `Config.DATA_DIR = os.path.abspath(...)` — the
    # secret-key file and the SQLite database are located from this.
    app.config["DATA_DIR"] = settings.data_dir
    app.config["KNOWN_DEFAULT_SECRETS"] = PLACEHOLDER_SECRETS
    app.config["JWT_EXPIRES"] = settings.jwt_expires
    app.config["MAX_UPLOAD_BYTES"] = settings.max_upload_bytes
    app.config["JSON_SORT_KEYS"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.sqlalchemy_uri
    # pool_pre_ping recycles connections a remote Postgres dropped (idle timeout,
    # restart). Harmless for SQLite. Enables the optional Postgres backend.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    # Stays a CALLABLE that creates the directory: three call sites invoke it as
    # `app.config["attachments_dir"]()`, and settings resolution is deliberately
    # side-effect free, so the mkdir lives here.
    app.config["attachments_dir"] = lambda: _ensure_dir(settings.attachments_dir)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
    for warning in settings.warnings:
        _LOGGER.warning("Configuration: %s", warning)
    _db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    _LOGGER.info("HomeHoard storage backend: %s",
                 "sqlite" if _db_uri.startswith("sqlite") else _db_uri.split("://", 1)[0])

    # Resolve the signing key BEFORE the fail-closed check below: an operator
    # value wins, otherwise reuse (or generate once and persist) a key under
    # DATA_DIR so restarts don't invalidate every session and API token.
    secret, generated = ensure_secret_key(
        app.config.get("SECRET_KEY") or "", app.config["DATA_DIR"])
    app.config["SECRET_KEY"] = secret
    if generated:
        _LOGGER.warning(
            "No HBOX_SECRET_KEY was supplied; generated one and persisted it to "
            "%s so sessions and API tokens survive restarts. Back this file up "
            "with your data.", os.path.join(app.config["DATA_DIR"], ".secret_key"))

    # Fail closed: never sign real tokens with a shipped default or a weak
    # (too-short) secret when authentication is enabled.
    if not app.config["DISABLE_AUTH"]:
        secret = app.config["SECRET_KEY"] or ""
        if secret in app.config["KNOWN_DEFAULT_SECRETS"] or len(secret) < 32:
            raise RuntimeError(
                "HBOX_SECRET_KEY is unset, a known default, or shorter than 32 "
                "characters. Set a strong random secret before enabling "
                "authentication (e.g. `openssl rand -base64 48`)."
            )
    if app.config["DISABLE_AUTH"]:
        _LOGGER.warning(
            "HBOX_DISABLE_AUTH is on: every request runs as the default user "
            "with NO authentication. Only expose this behind Home Assistant "
            "ingress or a trusted authenticating proxy."
        )

    # Trust N reverse proxies so rate limiting keys on the real client IP.
    hops = app.config["PROXY_HOPS"]
    if hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)

    # CORS: explicit allowlist only. Empty => same-origin (no CORS headers).
    origins = app.config["CORS_ORIGINS"]
    CORS(app, origins=origins or [], supports_credentials=bool(origins))

    db.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (register models)

    _init_schema(app)

    _register_request_context(app)
    _register_blueprints(app)
    _register_spa(app)
    _register_errors(app)
    _register_security_headers(app)

    from .worker import start_worker
    start_worker(app)  # background job poller (no-op when WORKER_ENABLED is False)
    return app


def _register_request_context(app):
    """Give every request a correlation id, and log the ones worth logging.

    The id is echoed as X-Request-Id and included in a 500 body, so a user can
    quote it in a bug report and it can be grepped straight out of the log.

    Only slow requests and server errors get a line: gunicorn's access log
    already records the ordinary ones, and writing a second line per request is
    how a household add-on fills its disk.
    """
    @app.before_request
    def _assign_request_id():
        incoming = request.headers.get("X-Request-Id", "")
        # Bounded and charset-checked: this value lands in every log line for
        # the request, so an attacker-supplied one must not be able to forge
        # log structure or bloat the file.
        if incoming and len(incoming) <= 64 and _SAFE_REQUEST_ID.fullmatch(incoming):
            rid = incoming
        else:
            rid = uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        g._started_at = time.monotonic()

    @app.after_request
    def _finish_request(resp):
        resp.headers.setdefault("X-Request-Id", request_id_var.get())
        started = getattr(g, "_started_at", None)
        if started is None:
            return resp
        elapsed_ms = int((time.monotonic() - started) * 1000)
        threshold = app.config.get("SLOW_REQUEST_MS", 1000)
        if resp.status_code >= 500 or (threshold >= 0 and elapsed_ms >= threshold):
            _LOGGER.warning("%s %s -> %s in %dms",
                            scrub(request.method), scrub(request.path),
                            resp.status_code, elapsed_ms)
        return resp


def _register_security_headers(app):
    """Baseline hardening headers on every response."""
    from .auth import _request_from_ingress

    @app.after_request
    def _set_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # Content Security Policy. 'unsafe-inline' for styles only — the app
        # uses many inline style attributes; scripts stay 'self'.
        csp = (
            "default-src 'self'; "
            # The ONLY third-party relaxation: the two hosts services/videos.py
            # will produce an embed URL for. Every other link opens in a new tab
            # instead of being framed, so no other origin is ever embedded.
            "frame-src https://www.youtube-nocookie.com https://player.vimeo.com; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'"
        )
        # Under HA ingress the app is legitimately framed by Home Assistant, so
        # anti-clickjacking is asserted only when the request is NOT from the
        # ingress peer. Keyed on the per-request ingress check, not auth mode:
        # disable_auth:false behind ingress is supported (ingress identity runs
        # even with auth on) and keying on auth mode there blanks the HA panel,
        # while a standalone disable_auth deployment behind a non-HA proxy is
        # still clickjackable and must get the headers.
        if not _request_from_ingress():
            csp += "; frame-ancestors 'self'"
            resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Content-Security-Policy", csp)
        # HSTS only over HTTPS (harmless/ignored over plain HTTP).
        if request.is_secure:
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp


def _init_schema(app):
    """Bring the schema to head via Alembic under an exclusive file lock so
    concurrent gunicorn workers don't race on a fresh DB. SQLite and Postgres."""
    import fcntl

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    lock_path = os.path.join(app.config["DATA_DIR"], ".schema-init.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # locking unsupported (rare FS) — Alembic is still safe to run.
        with app.app_context():
            _maybe_boot_migrate(app)
            _run_migrations(app)


def _warn_stranded_sqlite(app, db_filename):
    """Loudly warn when the app is about to serve a Postgres database (external or
    shared-add-on provisioned) while a populated local SQLite still sits in
    DATA_DIR and migrate_from_sqlite is OFF — i.e. the inventory would look empty
    and the existing data is stranded (recoverable, not deleted). Silent in the
    normal cases (SQLite target, or no local DB to strand)."""
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        return
    src_file = os.path.join(app.config["DATA_DIR"], db_filename)
    if not os.path.exists(src_file):
        return
    _LOGGER.warning(
        "A Postgres database is configured but migrate_from_sqlite is off, and a "
        "local %s still holds data. The app is serving Postgres, which may be "
        "empty — your SQLite data is intact but not shown. To copy it over, enable "
        "migrate_from_sqlite and restart once.", src_file)


def _maybe_boot_migrate(app):
    """HA add-on convenience: when HBOX_MIGRATE_FROM_SQLITE is on and the app is
    configured for an external (Postgres) DB, copy the local SQLite database into
    the EMPTY target before serving, then normal startup stamps it to baseline.

    Skips a non-empty target (already migrated). If the copy FAILS, it raises to
    abort startup rather than let the app adopt-and-serve the empty target while
    real data is stranded in SQLite — the operator sees the failure, the SQLite
    source is untouched, and a fixed retry (or reverting HBOX_DATABASE_URL) recovers."""
    if not app.config.get("MIGRATE_FROM_SQLITE"):
        _warn_stranded_sqlite(app, "homehoard.db")
        return
    target = app.config["SQLALCHEMY_DATABASE_URI"]
    if target.startswith("sqlite"):
        return  # not configured for an external DB — nothing to migrate to
    src_file = os.path.join(app.config["DATA_DIR"], "homehoard.db")
    if not os.path.exists(src_file):
        _LOGGER.info("migrate_from_sqlite: no local %s to migrate — skipping", src_file)
        return
    from .services.db_copy import TargetNotEmpty, copy_database
    try:
        report = copy_database(f"sqlite:///{src_file}", target)
        _LOGGER.warning("migrate_from_sqlite: copied %d rows from SQLite into the "
                        "external database", report["total"])
    except TargetNotEmpty:
        _LOGGER.info("migrate_from_sqlite: target already has data — skipping (done)")
    except Exception as exc:
        # Do NOT serve an empty database with data stranded in SQLite. Fail the
        # boot loudly; the SQLite source is intact — fix the target (or unset
        # HBOX_MIGRATE_FROM_SQLITE / revert HBOX_DATABASE_URL) and restart.
        raise RuntimeError(
            "migrate_from_sqlite failed and the target isn't populated; refusing to "
            f"start on an empty database (your SQLite data is intact): {exc}"
        ) from exc


def _run_migrations(app):
    """Run Alembic migrations to head. Three cases, all handled:
      * Fresh DB → upgrade runs the baseline (create_all) + any deltas.
      * Existing PRE-Alembic install (tables, no alembic_version) → fill gaps
        (missing tables via create_all, legacy SQLite fixes via _migrate), then
        stamp baseline so later deltas apply.
      * Already on Alembic → apply pending revisions.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "migrations"))
    # Pass the URL via attributes, NOT set_main_option: Alembic's ConfigParser would
    # try to %-interpolate a URL-encoded password (e.g. `%40` for '@') and crash.
    cfg.attributes["url"] = app.config["SQLALCHEMY_DATABASE_URI"]

    with db.engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current is None and inspect(db.engine).has_table("users"):
        db.create_all()      # any missing tables
        _migrate(app)        # legacy SQLite column adds / rebuilds / backfills
        command.stamp(cfg, "0001_baseline")
    command.upgrade(cfg, "head")


def _migrate(app):
    """Legacy additive SQLite migrations, used to bring a pre-Alembic database up
    to the baseline before it is stamped (see _run_migrations). Fresh databases
    get every column from the metadata-driven baseline; Postgres is created fresh,
    so this no-ops there (SQLite-guarded below).

    ``db.create_all`` never alters existing tables, so add any columns that were
    introduced after a database was first created, plus one-time data backfills.
    """
    from sqlalchemy import inspect, text

    if not db.engine.url.get_backend_name().startswith("sqlite"):
        return
    inspector = inspect(db.engine)
    wanted = {
        "qr_tags": {
            "source": "VARCHAR(16) DEFAULT 'generated'",
            "code": "VARCHAR(512) DEFAULT ''",
            "code_format": "VARCHAR(24) DEFAULT 'qr'",
        },
        "items": {
            "checked_out": "BOOLEAN DEFAULT 0",
            "checked_out_to": "VARCHAR(255) DEFAULT ''",
            "checked_out_at": "DATETIME",
            "checkout_due": "DATETIME",
        },
        "users": {"ha_user_id": "VARCHAR(255)"},
    }
    for table, columns in wanted.items():
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        with db.engine.begin() as conn:
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    # Backfill roles: promote the earliest user of any household with no owner, so
    # an existing admin isn't locked out of the now-owner-gated surfaces. Idempotent.
    if inspector.has_table("users"):
        with db.engine.begin() as conn:
            conn.execute(text("""
                UPDATE users SET is_owner = 1
                WHERE id IN (
                    SELECT (SELECT u2.id FROM users u2 WHERE u2.group_id = g.id
                            ORDER BY u2.created_at ASC, u2.id ASC LIMIT 1)
                    FROM groups g
                    WHERE NOT EXISTS (SELECT 1 FROM users o
                                      WHERE o.group_id = g.id AND o.is_owner = 1)
                )
            """))

    # Backfill code for pre-existing generated tags so resolution stays uniform.
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE qr_tags SET code = token WHERE (code IS NULL OR code = '')")
        )

    # attachments: introduced bin_id + made item_id nullable so bins can have
    # photos too. SQLite can't drop a NOT NULL constraint in place, so rebuild
    # the table (preserving existing rows) when the old shape is detected.
    if inspector.has_table("attachments"):
        cols = {c["name"]: c for c in inspector.get_columns("attachments")}
        needs_rebuild = "bin_id" not in cols or cols["item_id"]["nullable"] is False
        if needs_rebuild:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE attachments RENAME TO attachments_old"))
            db.create_all()  # recreate `attachments` with the new schema
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        'INSERT INTO attachments '
                        '(id, created_at, updated_at, type, "primary", '
                        ' item_id, bin_id, document_id) '
                        'SELECT id, created_at, updated_at, type, "primary", '
                        ' item_id, NULL, document_id FROM attachments_old'
                    )
                )
                conn.execute(text("DROP TABLE attachments_old"))

    # Multi-location: give every existing item an initial holding mirroring its
    # current placement, so holdings become the source of truth for per-placement
    # quantities without breaking single-placement reads. Idempotent — items that
    # already have a holding are skipped, so a re-run (or a fresh DB with no items)
    # is a no-op.
    if inspector.has_table("item_holdings") and inspector.has_table("items"):
        from .models import Item
        from .services.holdings import ensure_holding
        orphans = db.session.query(Item).filter(~Item.holdings.any()).all()
        for it in orphans:
            ensure_holding(it)
        if orphans:
            db.session.commit()


def _register_blueprints(app):
    from .api.attachments import bp as attachments_bp
    from .api.bins import bp as bins_bp
    from .api.chat import bp as chat_bp
    from .api.checkout import bp as checkout_bp
    from .api.groups import bp as groups_bp
    from .api.ha import bp as ha_bp
    from .api.holdings import bp as holdings_bp
    from .api.items import bp as items_bp
    from .api.jobs import bp as jobs_bp
    from .api.labels import bp as labels_bp
    from .api.locations import bp as locations_bp
    from .api.lookup import bp as lookup_bp
    from .api.maintenance import bp as maintenance_bp
    from .api.misc import bp as misc_bp
    from .api.notifiers import bp as notifiers_bp
    from .api.qrtags import bp as qrtags_bp
    from .api.reports import bp as reports_bp
    from .api.suggestions import bp as suggestions_bp
    from .api.tokens import bp as tokens_bp
    from .api.users import bp as users_bp

    prefix = "/api/v1"
    for bp in (
        users_bp,
        groups_bp,
        locations_bp,
        labels_bp,
        items_bp,
        holdings_bp,
        bins_bp,
        qrtags_bp,
        attachments_bp,
        maintenance_bp,
        notifiers_bp,
        misc_bp,
        ha_bp,
        lookup_bp,
        checkout_bp,
        tokens_bp,
        reports_bp,
        chat_bp,
        jobs_bp,
        suggestions_bp,
    ):
        app.register_blueprint(bp, url_prefix=prefix)


def _register_errors(app):
    @app.errorhandler(404)
    def not_found(e):
        from flask import request

        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return _serve_spa("index.html")

    @app.errorhandler(413)
    def too_large(e):
        # Names the limit and how to change it: "upload too large" with no
        # number is a dead end, and video hits this far more often than photos.
        limit = app.config.get("MAX_UPLOAD_MB", 50)
        return jsonify({
            "error": f"that file is larger than the {limit} MB upload limit. "
                     "Link to the video instead, or raise max_upload_mb in the "
                     "add-on configuration."
        }), 413

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "too many requests, slow down"}), 429

    @app.errorhandler(Exception)
    def unhandled(e):
        """Log the traceback deliberately and return a curated body.

        Flask's default already logs unhandled exceptions, but only if logging
        happens to be configured — which it was not until this release. Doing it
        explicitly also lets us hand the caller the request id, so "it broke
        once" becomes a line an operator can actually find in the log.

        The exception text is NEVER returned: a driver error can carry the
        database password.
        """
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            return e  # 404/413/429 etc. keep their own handlers and status

        rid = request_id_var.get()
        _LOGGER.exception("unhandled error [%s] %s %s", rid,
                          scrub(request.method), scrub(request.path))
        return jsonify({"error": "internal server error", "requestId": rid}), 500


# --- SPA serving ---------------------------------------------------------
_DEFAULT_FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))


def _frontend_dist() -> str:
    """Where the built SPA lives — read per request from the app's resolved
    settings (FRONTEND_DIST, blank = the location baked into the image).

    Deliberately NOT a module-level constant: resolving config at import time is
    the pattern this refactor removed, and it made `python3 -m app.config_check`
    die with a traceback on a bad config instead of reporting it cleanly.
    """
    return current_app.config.get("FRONTEND_DIST") or _DEFAULT_FRONTEND_DIST


def _serve_spa(path):
    _FRONTEND_DIST = _frontend_dist()
    # safe_join, not os.path.join: it rejects traversal ("../") and absolute
    # segments, returning None. os.path.join would happily build a path outside
    # the dist dir, letting the isfile() check probe for arbitrary files.
    # Nested asset paths ("assets/index-abc.js") are still served normally.
    full = safe_join(_FRONTEND_DIST, path) if path else None
    if full and os.path.isfile(full):
        return send_from_directory(_FRONTEND_DIST, path)
    index = os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.isfile(index):
        return send_from_directory(_FRONTEND_DIST, "index.html")
    return (
        (
            "<h1>HomeHoard API</h1><p>Frontend not built. "
            "API is available under <code>/api/v1</code>.</p>"
        ),
        200,
    )


def _register_spa(app):
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        return _serve_spa(path)
