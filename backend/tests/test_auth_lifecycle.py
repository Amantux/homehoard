"""Credential lifecycle: a password change revokes older JWTs; API keys can expire."""
from datetime import datetime, timedelta, timezone

import jwt

from app.extensions import db
from app.models import ApiToken, User

LOGIN = {"username": "t@t.com", "password": "password"}


def _old_jwt(app, seconds_ago=10):
    """A JWT for the test user minted `seconds_ago` — i.e. before any change made
    now. Minted by hand because a login in the same second as the change is
    deliberately still valid (iat has whole-second precision)."""
    with app.app_context():
        user = db.session.query(User).filter_by(email="t@t.com").one()
        iat = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        return "Bearer " + jwt.encode(
            {"sub": user.id, "iat": iat, "exp": iat + timedelta(hours=1)},
            app.config["SECRET_KEY"], algorithm="HS256",
        )


def _me(client, token):
    return client.get("/api/v1/users/self", headers={"Authorization": token})


def test_password_change_revokes_older_jwt_and_returns_a_fresh_one(app, auth_client):
    old = _old_jwt(app)
    assert _me(auth_client, old).status_code == 200
    r = auth_client.put(
        "/api/v1/users/change-password",
        json={"current": "password", "new": "new-password-123"},
        headers={"Authorization": old},
    )
    assert r.status_code == 200
    fresh = r.get_json()["token"]
    assert _me(auth_client, old).status_code == 401
    assert fresh.startswith("Bearer ")  # same shape /users/login returns
    assert _me(auth_client, fresh).status_code == 200


def test_jwt_minted_after_change_is_valid(app, auth_client):
    r = auth_client.put(
        "/api/v1/users/change-password",
        json={"current": "password", "new": "new-password-123"},
    )
    assert r.status_code == 200
    login = auth_client.post(
        "/api/v1/users/login",
        json={"username": "t@t.com", "password": "new-password-123"},
    )
    assert _me(auth_client, login.get_json()["token"]).status_code == 200


def test_wrong_current_password_changes_nothing(app, auth_client):
    old = _old_jwt(app)
    r = auth_client.put(
        "/api/v1/users/change-password",
        json={"current": "nope", "new": "new-password-123"},
    )
    assert r.status_code == 400
    assert _me(auth_client, old).status_code == 200


def _key(auth_client, **body):
    r = auth_client.post("/api/v1/tokens", json={"name": "k", **body})
    return r


def test_expired_api_key_is_rejected_unexpired_key_works(app, auth_client):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = _key(auth_client, expiresAt=future)
    assert r.status_code == 201
    body = r.get_json()
    assert body["expiresAt"] is not None
    raw = body["token"]
    assert _me(auth_client, f"Bearer {raw}").status_code == 200
    with app.app_context():
        row = db.session.get(ApiToken, body["id"])
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.session.commit()
    assert _me(auth_client, f"Bearer {raw}").status_code == 401


def test_past_or_garbage_expiry_on_create_is_422(auth_client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _key(auth_client, expiresAt=past).status_code == 422
    assert _key(auth_client, expiresAt="not-a-date").status_code == 422
    assert _key(auth_client, expiresAt=12345).status_code == 422


def test_no_expiry_serializes_null_and_works(auth_client):
    r = _key(auth_client, expiresAt=None)
    assert r.status_code == 201
    body = r.get_json()
    assert body["expiresAt"] is None
    assert _me(auth_client, f"Bearer {body['token']}").status_code == 200
    listed = auth_client.get("/api/v1/tokens").get_json()
    assert all("expiresAt" in t for t in listed)


def test_migration_0020_round_trips_with_data(app, auth_client):
    """Downgrade drops both columns without losing the FK-referenced users /
    api_tokens rows (SQLite table rebuild under foreign_keys=ON); upgrade
    re-adds them."""
    import os

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import inspect

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert _key(auth_client).status_code == 201
    with app.app_context():
        cfg = AlembicConfig(os.path.join(backend, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(backend, "migrations"))
        cfg.attributes["url"] = app.config["SQLALCHEMY_DATABASE_URI"]
        db.session.remove()
        db.engine.dispose()
        command.downgrade(cfg, "0019_quantity_numeric")
        insp = inspect(db.engine)
        assert "password_changed_at" not in {c["name"] for c in insp.get_columns("users")}
        assert "expires_at" not in {c["name"] for c in insp.get_columns("api_tokens")}
        command.upgrade(cfg, "head")
        insp = inspect(db.engine)
        assert "password_changed_at" in {c["name"] for c in insp.get_columns("users")}
        assert "expires_at" in {c["name"] for c in insp.get_columns("api_tokens")}
        assert db.session.query(User).filter_by(email="t@t.com").count() == 1
        assert db.session.query(ApiToken).count() == 1


def _stored_expiry(auth_client, value):
    r = _key(auth_client, expiresAt=value)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["expiresAt"]


def _set_tz(app, monkeypatch, tz):
    # Settings is frozen: wrap it, overriding only TZ.
    real = app.config["SETTINGS"]

    class _Settings:
        TZ = tz

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setitem(app.config, "SETTINGS", _Settings())


def test_date_only_expiry_is_end_of_day_in_household_zone(app, auth_client, monkeypatch):
    # "expires Jan 1" must survive all of Jan 1 locally, not die at 00:00 UTC.
    _set_tz(app, monkeypatch, "America/Los_Angeles")
    got = _stored_expiry(auth_client, "2099-01-01")
    assert datetime.fromisoformat(got.replace("Z", "+00:00")) == datetime(
        2099, 1, 2, 7, 59, 59, tzinfo=timezone.utc
    )


def test_date_only_expiry_in_utc_zone(app, auth_client, monkeypatch):
    _set_tz(app, monkeypatch, "UTC")
    got = _stored_expiry(auth_client, "2099-01-01")
    assert datetime.fromisoformat(got.replace("Z", "+00:00")) == datetime(
        2099, 1, 1, 23, 59, 59, tzinfo=timezone.utc
    )


def test_full_datetime_expiry_is_unchanged_by_zone(app, auth_client, monkeypatch):
    _set_tz(app, monkeypatch, "America/Los_Angeles")
    for value in ("2099-01-01T00:00:00Z", "2099-01-01T00:00:00"):
        got = _stored_expiry(auth_client, value)
        assert datetime.fromisoformat(got.replace("Z", "+00:00")) == datetime(
            2099, 1, 1, tzinfo=timezone.utc
        )


def test_date_only_expiry_for_yesterday_is_422(app, auth_client, monkeypatch):
    _set_tz(app, monkeypatch, "UTC")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    assert _key(auth_client, expiresAt=yesterday).status_code == 422
