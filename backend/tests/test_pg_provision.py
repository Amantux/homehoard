"""Shared-PostgreSQL auto-provisioning: DB-URL precedence + the startup client.

No network: the Supervisor/provision calls are monkeypatched. Configuration is
patched through the ENVIRONMENT rather than by setting Config attributes:
pg_provision resolves via app.settings.load_settings(), which is what the
entrypoint relies on now that the shell no longer translates options.json into
env vars. Patching Config would test nothing.
"""
import stat

import pytest

from app import pg_provision as pp
from app.settings import load_settings, normalize_db_url

PG_DSN = "postgresql+psycopg://homehoard:secret@local-shared-postgres:5432/homehoard"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """A clean temp data dir, shared-postgres off, no explicit DATABASE_URL.
    Individual tests flip the attributes they exercise."""
    monkeypatch.setenv("HBOX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HBOX_DATABASE_URL", raising=False)
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "false")
    monkeypatch.setenv("HBOX_POSTGRES_PROVISION_TOKEN", "")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    return tmp_path


def _forbid_network(monkeypatch):
    """Sentinels that record calls, so a short-circuit test fails loudly if it
    ever reaches the discovery/provision path."""
    calls = []
    monkeypatch.setattr(pp, "_discovery_config", lambda: calls.append("discovery"))
    monkeypatch.setattr(pp, "_candidate_provision_urls",
                        lambda cfg: (calls.append("urls"), [])[1])
    monkeypatch.setattr(pp, "_provision",
                        lambda url, token: calls.append("provision"))
    return calls


def _prime_reachable(monkeypatch, dsn):
    """Config + patched discovery/provision so main() reaches the write path."""
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    monkeypatch.setenv("HBOX_POSTGRES_PROVISION_TOKEN", "tok")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup")
    monkeypatch.setattr(pp, "_discovery_config",
                        lambda: {"provision_url": "http://x:8087/provision", "token": "tok"})
    monkeypatch.setattr(pp, "_candidate_provision_urls",
                        lambda cfg: ["http://x:8087/provision"])
    monkeypatch.setattr(pp, "_provision", lambda url, token: dsn)


# ---- database-URL precedence -------------------------------------

def test_uri_explicit_database_url_wins_over_provisioned(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    (cfg / ".database_url").write_text(PG_DSN)
    monkeypatch.setenv("HBOX_DATABASE_URL", "postgresql://u:p@host/db")
    assert load_settings().sqlalchemy_uri == "postgresql+psycopg://u:p@host/db"


def test_uri_reads_provisioned_dsn_when_flag_on(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    (cfg / ".database_url").write_text(PG_DSN + "\n")
    assert load_settings().sqlalchemy_uri == PG_DSN


def test_uri_ignores_provisioned_dsn_when_flag_off(cfg):
    (cfg / ".database_url").write_text(PG_DSN)
    assert load_settings().sqlalchemy_uri.startswith("sqlite:///")


def test_uri_sqlite_when_flag_on_but_no_file(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    assert load_settings().sqlalchemy_uri.startswith("sqlite:///")


def test_resolve_accepts_psycopg(cfg):
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_resolve_rejects_foreign_scheme(cfg):
    with pytest.raises(ValueError):
        normalize_db_url("mysql://u:p@host/db")


def test_resolve_rejects_non_psycopg_driver(cfg):
    with pytest.raises(ValueError):
        normalize_db_url("postgresql+asyncpg://u:p@host/db")


# ---- pg_provision.main() short-circuits (must not touch the network) ------

def test_main_noop_when_database_url_set(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_DATABASE_URL", PG_DSN)
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    calls = _forbid_network(monkeypatch)
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()
    assert calls == []


def test_main_noop_when_flag_off(cfg, monkeypatch):
    calls = _forbid_network(monkeypatch)
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()
    assert calls == []


def test_main_noop_when_already_provisioned(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    (cfg / pp.DSN_FILENAME).write_text(PG_DSN)
    calls = _forbid_network(monkeypatch)
    assert pp.main() == 0
    assert calls == []  # returned before discovery/provision


def test_main_noop_without_supervisor_token(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    # SUPERVISOR_TOKEN unset by the cfg fixture
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()


def test_main_noop_without_token(cfg, monkeypatch):
    monkeypatch.setenv("HBOX_USE_SHARED_POSTGRES", "true")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup")
    monkeypatch.setattr(pp, "_discovery_config", lambda: None)
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()


# ---- pg_provision writes --------------------------------------------------

def test_main_writes_dsn_0600_on_success(cfg, monkeypatch):
    _prime_reachable(monkeypatch, PG_DSN)
    assert pp.main() == 0
    path = cfg / pp.DSN_FILENAME
    assert path.read_text() == PG_DSN
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_main_rejects_foreign_dsn(cfg, monkeypatch):
    _prime_reachable(monkeypatch, "mysql://u:p@host/db")
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()


def test_main_stays_on_sqlite_when_existing_data_and_no_migrate(cfg, monkeypatch):
    # Existing populated SQLite + migrate_from_sqlite off → don't provision an empty
    # Postgres and strand the data; stay on SQLite (no network, no DSN written).
    (cfg / "homehoard.db").write_bytes(b"SQLite format 3\x00 with data")
    _prime_reachable(monkeypatch, PG_DSN)
    monkeypatch.setenv("HBOX_MIGRATE_FROM_SQLITE", "false")
    calls = _forbid_network(monkeypatch)
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()
    assert calls == []  # bailed before discovery/provision


def test_main_provisions_over_existing_data_when_migrate_on(cfg, monkeypatch):
    # With migrate_from_sqlite on, the boot-migrate step copies the data, so
    # provisioning proceeds even though a populated SQLite file exists.
    (cfg / "homehoard.db").write_bytes(b"SQLite format 3\x00 with data")
    _prime_reachable(monkeypatch, PG_DSN)
    monkeypatch.setenv("HBOX_MIGRATE_FROM_SQLITE", "true")
    assert pp.main() == 0
    assert (cfg / pp.DSN_FILENAME).read_text() == PG_DSN


def test_main_no_write_on_provision_error(cfg, monkeypatch):
    _prime_reachable(monkeypatch, PG_DSN)

    def boom(url, token):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pp, "_provision", boom)
    assert pp.main() == 0
    assert not (cfg / pp.DSN_FILENAME).exists()


# --- _warn_stranded_sqlite: the SQLite→Postgres transition safety net ----------

class _FakeApp:
    def __init__(self, uri, data_dir):
        self.config = {"SQLALCHEMY_DATABASE_URI": uri, "DATA_DIR": data_dir}


def test_warns_when_postgres_adopted_beside_populated_sqlite(tmp_path, caplog):
    import logging

    from app import _warn_stranded_sqlite
    (tmp_path / "homehoard.db").write_text("data")
    app = _FakeApp(PG_DSN, str(tmp_path))
    with caplog.at_level(logging.WARNING):
        _warn_stranded_sqlite(app, "homehoard.db")
    assert any("migrate_from_sqlite" in r.message for r in caplog.records)


def test_no_warning_on_sqlite_target(tmp_path, caplog):
    import logging

    from app import _warn_stranded_sqlite
    (tmp_path / "homehoard.db").write_text("data")
    app = _FakeApp(f"sqlite:///{tmp_path}/homehoard.db", str(tmp_path))
    with caplog.at_level(logging.WARNING):
        _warn_stranded_sqlite(app, "homehoard.db")
    assert not caplog.records


def test_no_warning_without_local_sqlite(tmp_path, caplog):
    import logging

    from app import _warn_stranded_sqlite
    app = _FakeApp(PG_DSN, str(tmp_path))
    with caplog.at_level(logging.WARNING):
        _warn_stranded_sqlite(app, "homehoard.db")
    assert not caplog.records
