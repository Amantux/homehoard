"""The Alembic schema-init path — fresh create AND the pre-Alembic ADOPTION/stamp
branch (the code that touches every existing install's database exactly once).

This is the riskiest code in the migration switch, so it gets direct coverage:
a future edit that breaks the stamp revision id, env.py URL passing, or the
create_all→stamp→upgrade ordering must fail here, not in production.
"""
import os

import pytest
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import _run_migrations
from app.config import Config
from app.extensions import db
from app.models import Group, User


def _revision():
    with db.engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _head():
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def test_fresh_db_is_at_head(app):
    with app.app_context():
        assert inspect(db.engine).has_table("alembic_version")
        assert _revision() == _head()


def test_pre_alembic_db_is_adopted_and_data_survives(app):
    with app.app_context():
        # Seed real data through the ORM (real constraints)…
        g = Group(name="H", currency="USD")
        db.session.add(g)
        db.session.flush()
        db.session.add(User(name="Alex", email="a@x.com", password_hash="x",
                            is_superuser=False, is_owner=True, group_id=g.id))
        db.session.commit()
        # …then simulate a PRE-Alembic install by removing the version marker.
        db.session.execute(text("DROP TABLE alembic_version"))
        db.session.commit()
        assert not inspect(db.engine).has_table("alembic_version")

        # Adoption: fill gaps → stamp baseline → upgrade to head, data intact.
        _run_migrations(app)

        assert _revision() == _head()  # reaches head (baseline + deltas)
        assert db.session.query(User).filter_by(email="a@x.com").count() == 1


def test_bare_config_resolves_the_env_database_url(monkeypatch, tmp_path):
    """`Config.sqlalchemy_uri()` called on Config itself — the branch
    migrations/env.py uses for the standalone `alembic` CLI. The subclass tests
    below exercise a different branch, so this one was uncovered.
    """
    monkeypatch.setenv("HBOX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HBOX_DATABASE_URL", "postgresql://u:p@h/db")

    assert Config.sqlalchemy_uri() == "postgresql+psycopg://u:p@h/db"


def test_bare_config_db_url_survives_an_unrelated_invalid_setting(monkeypatch, tmp_path):
    """Recovering a broken deployment with `alembic upgrade head` must not abort
    because CORS_ORIGINS or SECRET_KEY is wrong — it only asked which database."""
    monkeypatch.setenv("HBOX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HBOX_DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("HBOX_CORS_ORIGINS", "example.com")
    monkeypatch.setenv("HBOX_SECRET_KEY", "short")

    assert Config.sqlalchemy_uri() == "sqlite:///x.db"


def test_url_validation_and_normalization(tmp_path):
    assert Config._normalize_db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert Config._normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"

    class Base(Config):
        DATA_DIR = str(tmp_path)

    class Blank(Base):
        DATABASE_URL = "   "
    assert Blank.sqlalchemy_uri().startswith("sqlite")  # whitespace → SQLite default

    class Async(Base):
        DATABASE_URL = "postgresql+asyncpg://u@h/db"
    with pytest.raises(RuntimeError, match="psycopg"):
        Async.sqlalchemy_uri()

    class Mysql(Base):
        DATABASE_URL = "mysql://u@h/db"
    with pytest.raises(RuntimeError, match="unsupported"):
        Mysql.sqlalchemy_uri()


def test_dedupe_asset_ids_renumbers_duplicates():
    """The 0004 backfill gives duplicate per-group asset ids distinct values, keeping
    the oldest row's id and moving later duplicates to the group's next free id."""
    import importlib.util
    import os
    from sqlalchemy import create_engine, text

    here = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(here, "migrations", "versions", "0004_uq_items_group_asset.py")
    spec = importlib.util.spec_from_file_location("m0004", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE items(id TEXT PRIMARY KEY, group_id TEXT, "
                       "asset_id INT, created_at TEXT)"))
        for i, (g, a) in enumerate([("g1", 1), ("g1", 2), ("g1", 2), ("g2", 5)]):
            c.execute(text("INSERT INTO items VALUES(:i,:g,:a,:t)"),
                      {"i": f"id{i}", "g": g, "a": a, "t": f"2020-01-0{i + 1}"})
        m._dedupe_asset_ids(c)
        rows = c.execute(text("SELECT group_id, asset_id FROM items")).fetchall()

    g1 = sorted(a for g, a in rows if g == "g1")
    assert g1 == [1, 2, 3]          # the two dup 2s became 2 and 3
    assert [a for g, a in rows if g == "g2"] == [5]   # other group untouched
