"""Boot-migrate against a REAL Postgres (B15).

SQLite accepts schema that Postgres rejects (a Boolean `server_default` of
integer 0 broke every fresh Postgres install: B1), so the SQLite suite can't
catch this class of bug. Skipped unless HBOX_TEST_PG_URL points at an EMPTY,
throwaway Postgres database; CI's `postgres-schema` job provides one.
"""
import os
import uuid

import pytest
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import Group, Item, User

PG_URL = os.environ.get("HBOX_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="set HBOX_TEST_PG_URL to an empty throwaway Postgres to run")


def _head():
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def test_boot_migrate_on_postgres_reaches_head_with_working_defaults(monkeypatch):
    from app import create_app
    monkeypatch.setenv("HBOX_DATABASE_URL", PG_URL)
    app = create_app()  # runs _maybe_boot_migrate: alembic upgrade head
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        with db.engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == _head()

        g = Group(name="PG", currency="USD")
        db.session.add(g)
        db.session.flush()
        db.session.add(User(name="u", email=f"{uuid.uuid4().hex}@example.test",
                            password_hash="x", group_id=g.id))
        item = Item(name="Flour", group_id=g.id, asset_id=0)
        db.session.add(item)
        db.session.commit()
        assert item.hidden is False

        # The ORM fills `hidden` from its Python default; prove the DATABASE
        # default works too by copying the row with `hidden` left out.
        cols = [c["name"] for c in inspect(db.engine).get_columns("items")
                if c["name"] not in ("id", "hidden")]
        quote = db.engine.dialect.identifier_preparer.quote
        col_sql = ", ".join(quote(c) for c in cols)
        new_id = str(uuid.uuid4())
        with db.engine.begin() as conn:
            conn.execute(text(f"INSERT INTO items (id, {col_sql}) "
                              f"SELECT :new_id, {col_sql} FROM items WHERE id = :id"),
                         {"new_id": new_id, "id": item.id})
            assert conn.execute(text("SELECT hidden FROM items WHERE id = :id"),
                                {"id": new_id}).scalar() is False
