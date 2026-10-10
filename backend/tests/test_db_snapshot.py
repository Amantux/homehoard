"""Pre-upgrade SQLite snapshot (app/db_snapshot.py, wired in _run_migrations).

An upgrade that fails or is SIGKILLed mid-DDL must never leave the user
without a copy of their data, and a snapshot that can't be written must stop
the upgrade rather than let it run unprotected.
"""
import glob
import os
import sqlite3

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app import _run_migrations
from app import db_snapshot
from app.db_snapshot import SnapshotError, snapshot_sqlite
from app.extensions import db
from app.models import Group, Item

OLD = "0018_maintenance_recurrence"


def _cfg(url):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "migrations"))
    cfg.attributes["url"] = url
    return cfg


def _rev():
    with db.engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _snaps(app):
    return sorted(glob.glob(os.path.join(app.config["DATA_DIR"], "backups",
                                         "pre-upgrade-*.db")))


def _seed_at_old_revision(app):
    """An item on a DB downgraded to OLD — an install about to be upgraded."""
    g = Group(name="H", currency="USD")
    db.session.add(g)
    db.session.flush()
    db.session.add(Item(name="Flour", group_id=g.id, asset_id=0))
    db.session.commit()
    cfg = _cfg(app.config["SQLALCHEMY_DATABASE_URI"])
    db.session.remove()
    db.engine.dispose()
    command.downgrade(cfg, OLD)
    assert _rev() == OLD
    return cfg


def test_upgrade_snapshots_the_old_db_first(app):
    with app.app_context():
        cfg = _seed_at_old_revision(app)
        _run_migrations(app)

        assert _rev() == ScriptDirectory.from_config(cfg).get_current_head()
        snaps = _snaps(app)
        assert len(snaps) == 1
        assert os.path.basename(snaps[0]).startswith(f"pre-upgrade-{OLD}-")
        assert os.stat(snaps[0]).st_mode & 0o777 == 0o600
        con = sqlite3.connect(snaps[0])
        try:
            assert con.execute("SELECT name FROM items").fetchall() == [("Flour",)]
            assert con.execute("SELECT version_num FROM alembic_version"
                               ).fetchone() == (OLD,)
        finally:
            con.close()


def test_db_already_at_head_takes_no_snapshot(app):
    with app.app_context():
        _run_migrations(app)
        assert _snaps(app) == []


def test_rotation_keeps_the_newest_two(app, tmp_path):
    with app.app_context():
        src = db.engine.url.database
        made = [snapshot_sqlite(src, str(tmp_path), OLD) for _ in range(3)]
        left = _snaps(app)
        assert len(left) == 2
        assert made[0] not in left and set(made[1:]) == set(left)


def test_snapshot_failure_refuses_to_migrate(app, monkeypatch):
    with app.app_context():
        _seed_at_old_revision(app)

        class _Boom:
            def __init__(self, *_a):
                self._real = _real_connect(*_a)

            def backup(self, _dst):
                raise sqlite3.OperationalError("database or disk is full")

            def close(self):
                self._real.close()

        _real_connect = sqlite3.connect
        monkeypatch.setattr(db_snapshot.sqlite3, "connect", _Boom)

        with pytest.raises(SnapshotError) as exc:
            _run_migrations(app)
        # Curated message, not the driver's text; no half-written snapshot left.
        assert "NOT applied" in str(exc.value)
        assert "disk is full" not in str(exc.value)
        assert _snaps(app) == []
        db.engine.dispose()
        assert _rev() == OLD
        with db.engine.connect() as conn:
            assert conn.execute(text("SELECT name FROM items")).fetchall() == [("Flour",)]
