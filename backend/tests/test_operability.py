"""Production-operability: readiness vs liveness, SQLite durability pragmas,
and an end-to-end backup → restore-verification round trip."""
import json
import os
import subprocess
import sys

from sqlalchemy import text

from app import create_app
from app.config import Config
from app.extensions import db

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_status_is_liveness_only(client):
    # Liveness must not touch dependencies and always answers while the process
    # is up.
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    assert r.get_json()["health"] is True


def test_ready_reports_dependencies_ok(client):
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ready"] is True
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["storage"] == "ok"


def test_ready_returns_503_when_db_unavailable(client, monkeypatch):
    # Fault injection: the DB check raises → readiness must fail (503), not 200,
    # and must not leak a stack trace.
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "execute", boom)
    r = client.get("/api/v1/ready")
    assert r.status_code == 503
    body = r.get_json()
    assert body["ready"] is False
    assert body["checks"]["database"] == "error"
    assert "db down" not in r.get_data(as_text=True)  # no internals leaked


def test_sqlite_wal_and_foreign_keys_enabled(app):
    with app.app_context():
        mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
        fk = db.session.execute(text("PRAGMA foreign_keys")).scalar()
        assert str(mode).lower() == "wal"
        assert int(fk) == 1


def test_delete_user_with_owned_rows_succeeds_under_fk_enforcement(auth_client):
    # Regression: foreign_keys=ON must not RESTRICT account deletion when the
    # user owns cascade-able rows (API tokens, notifiers). Would 500 without the
    # ORM cascades on User.api_tokens / User.notifiers.
    assert auth_client.post("/api/v1/tokens", json={"name": "k"}).status_code == 201
    assert auth_client.post(
        "/api/v1/notifiers", json={"name": "n", "url": "tgram://a/b"}
    ).status_code == 201
    assert auth_client.delete("/api/v1/users/self").status_code == 204


def test_backup_and_restore_verification_roundtrip(tmp_path):
    """DR gate: seed a data dir, back it up, then run the restore-verifier and
    require it to PASS (checksums, integrity, app boot, count match)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    class SeedConfig(Config):
        DATA_DIR = str(data_dir)
        DATABASE_URL = None
        DISABLE_AUTH = True
        RATELIMIT_ENABLED = False

    seed_app = create_app(SeedConfig)
    c = seed_app.test_client()
    for name in ("Drill", "Hammer", "Wrench"):
        assert c.post("/api/v1/items", json={"name": name}).status_code == 201
    # Fold the WAL into the main DB file so the online backup captures everything.
    with seed_app.app_context():
        db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        db.session.commit()

    backup_dir = tmp_path / "backup"
    report = tmp_path / "report.json"
    env = {**os.environ, "PYTHONPATH": os.path.join(_REPO, "backend")}

    b = subprocess.run(
        [sys.executable, os.path.join(_REPO, "scripts", "backup.py"),
         "--data-dir", str(data_dir), "--out", str(backup_dir)],
        capture_output=True, text=True, env=env,
    )
    assert b.returncode == 0, b.stderr

    r = subprocess.run(
        [sys.executable, os.path.join(_REPO, "scripts", "restore_verify.py"),
         "--backup", str(backup_dir), "--report", str(report)],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads(report.read_text())
    assert result["passed"] is True
    names = {ch["name"]: ch["ok"] for ch in result["checks"]}
    assert names["integrity_check"] and names["item_count_matches_backup"]
    # 3 items seeded → 3 restored.
    detail = next(ch["detail"] for ch in result["checks"]
                  if ch["name"] == "item_count_matches_backup")
    assert "restored=3" in detail
