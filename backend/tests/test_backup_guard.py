"""Writes are refused while an HA backup is in progress (app/backup_guard.py)."""
import os
import time

import pytest

from app.backup_guard import BACKUP_FLAG_MAX_AGE, BackupInProgress, FLAG
from app.extensions import db
from app.models import User


def _set_flag(app, age=0):
    path = os.path.join(app.config["DATA_DIR"], FLAG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def test_a_write_during_a_backup_gets_a_curated_503(app, auth_client):
    _set_flag(app)
    r = auth_client.post("/api/v1/items", json={"name": "Clock"})
    assert r.status_code == 503
    body = r.get_json()
    assert body["error"] == "A Home Assistant backup is in progress. Try again in a moment."
    assert body["requestId"]
    assert r.headers["Retry-After"] == "10"


def test_reads_still_work_during_a_backup(app, auth_client):
    _set_flag(app)
    assert auth_client.get("/api/v1/items").status_code == 200


def test_login_still_works_during_a_backup(app, auth_client, client):
    _set_flag(app)
    r = client.post("/api/v1/users/login", json={"username": "t@t.com", "password": "password"})
    assert r.status_code == 200
    assert r.get_json()["token"]


def test_writes_work_without_the_flag(auth_client):
    assert auth_client.post("/api/v1/items", json={"name": "Clock"}).status_code == 201


def test_a_stale_flag_is_ignored_and_removed(app, auth_client):
    flag = _set_flag(app, age=BACKUP_FLAG_MAX_AGE + 60)
    copy = os.path.join(app.config["DATA_DIR"], "backups", "ha-backup.db")
    open(copy, "w").close()
    assert auth_client.post("/api/v1/items", json={"name": "Clock"}).status_code == 201
    assert not os.path.exists(flag)
    # Writes resumed, so the old copy must not be promoted over them at boot.
    assert not os.path.exists(copy)


def test_the_flush_backstop_refuses_writes_outside_a_request(app, auth_client):
    _set_flag(app)
    with app.app_context():
        user = db.session.execute(db.select(User)).scalars().first()
        user.name = "Changed"
        with pytest.raises(BackupInProgress):
            db.session.commit()
        db.session.rollback()


def test_an_api_key_can_still_read_during_a_backup(app, auth_client, client):
    """Key auth bumps last_used_at; that refused write must not fail the read."""
    key = auth_client.post("/api/v1/tokens", json={"name": "reader"}).get_json()["token"]
    _set_flag(app)
    del client.environ_base["HTTP_AUTHORIZATION"]
    r = client.get("/api/v1/items", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200


def test_writes_are_refused_before_the_view_runs(app, auth_client):
    """The request layer answers first: a delete of a missing item gets the
    backup 503, not a 404 (the flush backstop alone never sees a write)."""
    assert auth_client.delete("/api/v1/items/999999").status_code == 404
    _set_flag(app)
    r = auth_client.delete("/api/v1/items/999999")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "10"
