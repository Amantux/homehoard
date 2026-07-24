"""Whole-database copy (SQLite -> Postgres migration).

The cross-engine copy is exercised SQLite -> SQLite (a live Postgres server isn't
available in this suite); the Postgres-specific type handling rides on the typed
metadata + the all-tables Postgres-DDL compile check elsewhere.
"""
import pytest
from sqlalchemy import create_engine, func, select

from app import _maybe_boot_migrate
from app.auth import create_token
from app.extensions import db
from app.models import Group, Item, Location, User
from app.services.db_copy import (DbCopyError, TargetNotEmpty, _order_for_self_fk,
                                  copy_database, migrate_sqlite_to_postgres)


def _seed(app):
    with app.app_context():
        g = Group(name="H", currency="usd")
        db.session.add(g)
        db.session.flush()
        db.session.add(User(name="Alex", email="a@x.com", password_hash="x",
                            is_superuser=False, is_owner=True, group_id=g.id))
        db.session.add(Item(name="Drill", group_id=g.id))
        db.session.commit()
        return db.session.query(User).filter_by(email="a@x.com").first().id


def test_copy_preserves_all_tables_ids_and_counts(app, tmp_path):
    user_id = _seed(app)
    target = f"sqlite:///{tmp_path}/target.db"

    report = copy_database(app.config["SQLALCHEMY_DATABASE_URI"], target)

    assert report["ok"] and report["tables"]["users"] == 1
    assert set(report["tables"]) == {t.name for t in db.metadata.sorted_tables}
    eng = create_engine(target)
    with eng.connect() as c:
        assert c.execute(select(func.count()).select_from(User.__table__)).scalar() == 1
        row = c.execute(select(User.__table__.c.id, User.__table__.c.email)).first()
    assert row[0] == user_id and row[1] == "a@x.com"  # id + data preserved
    eng.dispose()


def test_order_for_self_fk_puts_parents_first():
    rows = [{"id": "c", "parent_id": "p", "name": "child"},
            {"id": "p", "parent_id": None, "name": "parent"}]
    ids = [r["id"] for r in _order_for_self_fk(Location.__table__, rows)]
    assert ids.index("p") < ids.index("c")


def test_copy_preserves_nested_locations(app, tmp_path):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    # Enforce FKs per-row on every connection (Postgres semantics), so this fails
    # if the self-FK parent-before-child ordering isn't applied in the copy loop.
    def _fk(dbapi, _):
        try:
            dbapi.execute("PRAGMA foreign_keys=ON")
        except Exception:  # noqa: BLE001
            pass
    event.listen(Engine, "connect", _fk)
    try:
        with app.app_context():
            g = Group(name="H", currency="usd")
            db.session.add(g)
            db.session.flush()
            # Build child FIRST (lower rowid, null parent), then the parent, then
            # link — so the natural read order is child-before-parent. Without the
            # reordering the FK-enforced insert would fail; this is the real guard.
            child = Location(name="Shelf", group_id=g.id)
            db.session.add(child)
            db.session.flush()
            parent = Location(name="Garage", group_id=g.id)
            db.session.add(parent)
            db.session.flush()
            child.parent_id = parent.id
            db.session.commit()
            parent_id = parent.id
        target = f"sqlite:///{tmp_path}/nested.db"

        report = copy_database(app.config["SQLALCHEMY_DATABASE_URI"], target)

        assert report["tables"]["locations"] == 2
        eng = create_engine(target)
        with eng.connect() as c:
            links = dict(c.execute(select(Location.__table__.c.name,
                                          Location.__table__.c.parent_id)).all())
        assert links["Shelf"] == parent_id  # child still points at its parent
        eng.dispose()
    finally:
        event.remove(Engine, "connect", _fk)


def test_endpoint_forbidden_for_non_owner(app):
    with app.app_context():
        g = Group(name="H", currency="usd")
        db.session.add(g)
        db.session.flush()
        member = User(name="Mem", email="m@x.com", password_hash="x",
                      is_superuser=False, is_owner=False, group_id=g.id)
        db.session.add(member)
        db.session.commit()
        token = create_token(member)
    r = app.test_client().post(
        "/api/v1/migrate/postgres", json={"targetUrl": "postgresql://u@h/db"},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_copy_refuses_non_empty_target(app, tmp_path):
    _seed(app)
    target = f"sqlite:///{tmp_path}/t.db"
    copy_database(app.config["SQLALCHEMY_DATABASE_URI"], target)

    with pytest.raises(TargetNotEmpty):
        copy_database(app.config["SQLALCHEMY_DATABASE_URI"], target)


def test_migrate_policy_rejects_bad_endpoints(app):
    with pytest.raises(DbCopyError, match="SQLite"):
        migrate_sqlite_to_postgres("postgresql+psycopg://u@h/db", "postgresql://u@h/db2")
    with pytest.raises(DbCopyError, match="postgresql"):
        migrate_sqlite_to_postgres("sqlite:///x.db", "mysql://u@h/db")


def test_endpoint_requires_target(auth_client):
    r = auth_client.post("/api/v1/migrate/postgres", json={})
    assert r.status_code == 400


def test_endpoint_rejects_non_postgres_target(auth_client):
    r = auth_client.post("/api/v1/migrate/postgres", json={"targetUrl": "sqlite:///x.db"})
    assert r.status_code == 400
    assert "postgresql" in r.get_json()["error"]


def test_endpoint_requires_auth(client):
    assert client.post("/api/v1/migrate/postgres", json={"targetUrl": "x"}).status_code == 401


def test_boot_migrate_noops_when_disabled(app):
    with app.app_context():
        app.config["MIGRATE_FROM_SQLITE"] = False
        _maybe_boot_migrate(app)


def test_boot_migrate_skips_without_source_file(app, tmp_path):
    with app.app_context():
        app.config["MIGRATE_FROM_SQLITE"] = True
        app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg://u:p@127.0.0.1:5432/none"
        app.config["DATA_DIR"] = str(tmp_path)  # no homehoard.db here → skip before connecting
        _maybe_boot_migrate(app)


def test_boot_migrate_raises_on_failure(app, tmp_path, monkeypatch):
    # A failed boot migrate must ABORT startup, not let the app adopt+serve the
    # empty target with data stranded in SQLite.
    import app.services.db_copy as dbc
    (tmp_path / "homehoard.db").write_bytes(b"x")  # source present

    def boom(*a, **k):
        raise RuntimeError("copy failed")
    monkeypatch.setattr(dbc, "copy_database", boom)
    with app.app_context():
        app.config["MIGRATE_FROM_SQLITE"] = True
        app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg://u:p@127.0.0.1:5432/none"
        app.config["DATA_DIR"] = str(tmp_path)
        with pytest.raises(RuntimeError, match="refusing to start"):
            _maybe_boot_migrate(app)
