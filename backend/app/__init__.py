"""HomeHoard application factory.

A Python (Flask) port of homebox — the inventory & organization system for the
home user. Ships an optional-auth JSON API under ``/api/v1`` and serves the
built Vue SPA.
"""
import logging
import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import db, limiter

_LOGGER = logging.getLogger("homehoard")


def create_app(config_object=Config):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_object)
    app.config["SQLALCHEMY_DATABASE_URI"] = config_object.sqlalchemy_uri()
    app.config["attachments_dir"] = config_object.attachments_dir
    app.config["MAX_CONTENT_LENGTH"] = config_object.MAX_UPLOAD_BYTES

    # Fail closed: never sign real tokens with a shipped default secret.
    if (
        not app.config["DISABLE_AUTH"]
        and app.config["SECRET_KEY"] in app.config["KNOWN_DEFAULT_SECRETS"]
    ):
        raise RuntimeError(
            "HBOX_SECRET_KEY is unset or a known default. Set a strong random "
            "secret (>=32 bytes) before enabling authentication."
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

    with app.app_context():
        db.create_all()
        _migrate(app)

    _register_blueprints(app)
    _register_spa(app)
    _register_errors(app)
    _register_security_headers(app)
    return app


def _register_security_headers(app):
    """Baseline hardening headers on every response."""
    disable_auth = app.config["DISABLE_AUTH"]

    @app.after_request
    def _set_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # Content Security Policy. 'unsafe-inline' for styles only — the app
        # uses many inline style attributes; scripts stay 'self'.
        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'"
        )
        # Under HA ingress the app is legitimately framed by Home Assistant, so
        # only assert anti-clickjacking when running standalone (auth enabled).
        if not disable_auth:
            csp += "; frame-ancestors 'self'"
            resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Content-Security-Policy", csp)
        # HSTS only over HTTPS (harmless/ignored over plain HTTP).
        if request.is_secure:
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp


def _migrate(app):
    """Additive schema migrations for existing SQLite databases.

    ``db.create_all`` never alters existing tables, so add any columns that
    were introduced after a database was first created.
    """
    from sqlalchemy import text, inspect

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
    }
    for table, columns in wanted.items():
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        with db.engine.begin() as conn:
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
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


def _register_blueprints(app):
    from .api.users import bp as users_bp
    from .api.groups import bp as groups_bp
    from .api.locations import bp as locations_bp
    from .api.labels import bp as labels_bp
    from .api.items import bp as items_bp
    from .api.bins import bp as bins_bp
    from .api.qrtags import bp as qrtags_bp
    from .api.attachments import bp as attachments_bp
    from .api.maintenance import bp as maintenance_bp
    from .api.notifiers import bp as notifiers_bp
    from .api.misc import bp as misc_bp
    from .api.ha import bp as ha_bp
    from .api.lookup import bp as lookup_bp
    from .api.checkout import bp as checkout_bp
    from .api.tokens import bp as tokens_bp

    prefix = "/api/v1"
    for bp in (
        users_bp,
        groups_bp,
        locations_bp,
        labels_bp,
        items_bp,
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
        return jsonify({"error": "upload too large"}), 413

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "too many requests, slow down"}), 429


# --- SPA serving ---------------------------------------------------------
_FRONTEND_DIST = os.environ.get(
    "HBOX_FRONTEND_DIST",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")),
)


def _serve_spa(path):
    full = os.path.join(_FRONTEND_DIST, path)
    if path and os.path.isfile(full):
        return send_from_directory(_FRONTEND_DIST, path)
    index = os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.isfile(index):
        return send_from_directory(_FRONTEND_DIST, "index.html")
    return (
        "<h1>HomeHoard API</h1><p>Frontend not built. "
        "API is available under <code>/api/v1</code>.</p>",
        200,
    )


def _register_spa(app):
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        return _serve_spa(path)
