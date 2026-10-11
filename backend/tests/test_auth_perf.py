"""Auth hot-path cost and resilience (P34: B3, B23)."""
from sqlalchemy.exc import OperationalError

import app.auth as auth
from app.extensions import db


def _count_verifies(monkeypatch):
    calls = []
    real = auth.verify_password

    def counting(password, hashed):
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(auth, "verify_password", counting)
    monkeypatch.setattr(auth, "_ROTATION_CHECKED", set())
    return calls


def test_backdoor_check_runs_once_per_user_hash_not_per_request(noauth_app, monkeypatch):
    client = noauth_app.test_client()
    # Warm-up: the first open-mode request may CREATE the local user, which
    # skips the rotation check entirely — count only requests against an
    # existing row.
    assert client.get("/api/v1/items").status_code == 200
    calls = _count_verifies(monkeypatch)

    assert client.get("/api/v1/items").status_code == 200
    assert client.get("/api/v1/items").status_code == 200
    assert len(calls) == 1

    # A changed hash (rotation, password change) is a new key: re-checked once.
    with noauth_app.app_context():
        user = db.session.query(auth.User).filter_by(email=auth.DEFAULT_EMAIL).one()
        user.password_hash = auth.hash_password("something-else")
        db.session.commit()
    assert client.get("/api/v1/items").status_code == 200
    assert client.get("/api/v1/items").status_code == 200
    assert len(calls) == 2


def test_backdoor_hash_seeded_after_check_is_still_rotated(noauth_app, monkeypatch):
    # The memo must not let a later write of the backdoor hash slip through.
    client = noauth_app.test_client()
    assert client.get("/api/v1/items").status_code == 200
    _count_verifies(monkeypatch)
    assert client.get("/api/v1/items").status_code == 200

    with noauth_app.app_context():
        user = db.session.query(auth.User).filter_by(email=auth.DEFAULT_EMAIL).one()
        user.password_hash = auth.hash_password("unused")
        db.session.commit()
    assert client.get("/api/v1/items").status_code == 200
    with noauth_app.app_context():
        user = db.session.query(auth.User).filter_by(email=auth.DEFAULT_EMAIL).one()
        assert not auth.verify_password("unused", user.password_hash)


def test_last_used_at_commit_failure_does_not_fail_the_request(app, auth_client, monkeypatch):
    raw = auth_client.post("/api/v1/tokens", json={"name": "HA"}).get_json()["token"]
    fresh = app.test_client()

    def boom():
        raise OperationalError("UPDATE api_tokens", {}, Exception("database is locked"))

    with app.app_context():
        monkeypatch.setattr(db.session, "commit", boom)
        r = fresh.get("/api/v1/items", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
