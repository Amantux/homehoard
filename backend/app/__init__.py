"""Shelfie application factory.

A Python (Flask) port of homebox — the inventory & organization system for the
home user. Ships an optional-auth JSON API under ``/api/v1`` and serves the
built Vue SPA.
"""
import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from .config import Config
from .extensions import db


def create_app(config_object=Config):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_object)
    app.config["SQLALCHEMY_DATABASE_URI"] = config_object.sqlalchemy_uri()
    app.config["attachments_dir"] = config_object.attachments_dir
    app.config["MAX_CONTENT_LENGTH"] = config_object.MAX_UPLOAD_BYTES

    CORS(app, supports_credentials=True)
    db.init_app(app)

    from . import models  # noqa: F401  (register models)

    with app.app_context():
        db.create_all()
        _migrate(app)

    _register_blueprints(app)
    _register_spa(app)
    _register_errors(app)
    return app


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
        "<h1>Shelfie API</h1><p>Frontend not built. "
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
