"""The Alembic schema-init path — fresh create AND the pre-Alembic ADOPTION/stamp
branch (the code that touches every existing install's database exactly once).

This is the riskiest code in the migration switch, so it gets direct coverage:
a future edit that breaks the stamp revision id, env.py URL passing, or the
create_all→stamp→upgrade ordering must fail here, not in production.
"""
import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app import _run_migrations
from app.config import Config
from app.extensions import db
from app.models import Group, User


def _revision():
    with db.engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_fresh_db_is_at_head(app):
    with app.app_context():
        assert inspect(db.engine).has_table("alembic_version")
        assert _revision() == "0001_baseline"


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

        assert _revision() == "0001_baseline"
        assert db.session.query(User).filter_by(email="a@x.com").count() == 1


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
