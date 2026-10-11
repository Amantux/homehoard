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


# ---- P91b: reads never 503, jobs requeue, bulk writes refused ----------------
from datetime import timedelta  # noqa: E402

from app import create_app  # noqa: E402
from app import auth as _auth  # noqa: E402
from app.config import Config  # noqa: E402
from app.models import Item, Job, VaultUnlock  # noqa: E402
from app.services import jobs  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

_INGRESS = {"REMOTE_ADDR": "172.30.32.2"}


@pytest.fixture()
def iapp(tmp_path):
    class C(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/ig.db"
        DISABLE_AUTH = True
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0

    app = create_app(C)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _ingress_get(c, ha, name):
    return c.get("/api/v1/me", environ_overrides=_INGRESS,
                 headers={"X-Remote-User-Id": ha, "X-Remote-User-Display-Name": name})


def test_ingress_name_refresh_is_skipped_not_503_during_a_backup(iapp):
    c = iapp.test_client()
    assert _ingress_get(c, "ha1", "Alice").status_code == 200
    _set_flag(iapp)
    r = _ingress_get(c, "ha1", "Alice Renamed")
    assert r.status_code == 200
    with iapp.app_context():
        assert db.session.query(User).filter_by(ha_user_id="ha1").one().name == "Alice"


def test_backdoor_rotation_is_skipped_not_503_during_a_backup(iapp):
    c = iapp.test_client()
    assert _ingress_get(c, "ha1", "Alice").status_code == 200
    with iapp.app_context():
        u = db.session.query(User).filter_by(ha_user_id="ha1").one()
        u.password_hash = _auth.hash_password(_auth._KNOWN_BACKDOOR_PASSWORD)
        db.session.commit()
        old = u.password_hash
    _auth._ROTATION_CHECKED.clear()
    _set_flag(iapp)
    assert _ingress_get(c, "ha1", "Alice").status_code == 200
    with iapp.app_context():
        # Not rotated yet, and not marked checked: the next request retries.
        assert db.session.query(User).filter_by(ha_user_id="ha1").one().password_hash == old
    assert not any(h == old for _, h in _auth._ROTATION_CHECKED)


def test_a_brand_new_ingress_user_during_a_backup_gets_the_curated_503(iapp):
    # Documented trade-off: provisioning is a write, so a first-ever load in
    # the seconds a backup runs is refused cleanly rather than half-done.
    c = iapp.test_client()
    assert _ingress_get(c, "ha1", "Alice").status_code == 200  # household exists
    _set_flag(iapp)
    r = _ingress_get(c, "ha2", "Bob")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "10"


def _expired_unlock_with_hidden_item(app, auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Secret Telescope"}).get_json()
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})
    assert auth_client.post("/api/v1/vault/unlock",
                            json={"phrase": "open sesame"}).status_code == 200
    with app.app_context():
        db.session.get(Item, item["id"]).hidden = True
        for row in db.session.query(VaultUnlock).all():
            row.expires_at = utcnow().replace(tzinfo=None) - timedelta(minutes=1)
        db.session.commit()


def test_an_expired_vault_unlock_reads_as_locked_during_a_backup(app, auth_client):
    _expired_unlock_with_hidden_item(app, auth_client)
    _set_flag(app)
    r = auth_client.get("/api/v1/items")
    assert r.status_code == 200
    assert "Secret Telescope" not in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(VaultUnlock).count() == 1  # left for later


def test_an_expired_vault_unlock_is_deleted_without_the_flag(app, auth_client):
    _expired_unlock_with_hidden_item(app, auth_client)
    r = auth_client.get("/api/v1/items")
    assert r.status_code == 200
    assert "Secret Telescope" not in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(VaultUnlock).count() == 0


def test_logout_works_during_a_backup(app, auth_client):
    _set_flag(app)
    assert auth_client.post("/api/v1/users/logout").status_code == 200


def test_vault_lock_is_refused_during_a_backup(app, auth_client):
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    _set_flag(app)
    # Called directly as well as via the API (whose before_request 503s first):
    # the bulk Query.delete bypasses before_flush, so only the explicit check
    # in the service stops it.
    with app.app_context():
        from app.services import vault
        with pytest.raises(BackupInProgress):
            vault.lock_all_for_user(db.session.query(VaultUnlock).one().user_id)
    assert auth_client.post("/api/v1/vault/lock").status_code == 503
    with app.app_context():
        assert db.session.query(VaultUnlock).count() == 1


def test_reap_stale_refuses_during_a_backup(app, auth_client, gid):
    with app.app_context():
        j = Job(kind="enrich", group_id=gid, status="running",
                started_at=utcnow() - timedelta(hours=1))
        db.session.add(j)
        db.session.commit()
        _set_flag(app)
        with pytest.raises(BackupInProgress):
            jobs.reap_stale()
        assert db.session.get(Job, j.id).status == "running"


def test_a_job_interrupted_by_a_backup_is_requeued_not_errored(app, auth_client, gid,
                                                               monkeypatch):
    calls = []

    def handler(job):
        calls.append(job.id)
        if len(calls) == 1:
            _set_flag(app)  # `pre` runs mid-job
            job.done = 1
            db.session.flush()
        return {"ok": True}

    monkeypatch.setitem(jobs._HANDLERS, "enrich", handler)
    with app.app_context():
        jid = jobs.enqueue("enrich", gid).id
        jobs.run_job(jobs.claim_one())
        assert db.session.get(Job, jid).status == "running"  # not "error"

        os.remove(os.path.join(app.config["DATA_DIR"], FLAG))  # `post`
        db.session.get(Job, jid).started_at = utcnow() - timedelta(hours=1)
        db.session.commit()  # (heartbeats stopped; the stale window passed)
        assert jobs.reap_stale() == 1
        jobs.run_job(jobs.claim_one())
        assert db.session.get(Job, jid).status == "done"
