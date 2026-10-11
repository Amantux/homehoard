"""The login/register rate limits actually fire.

Every other test runs with RATELIMIT_ENABLED=False, so without this file the
@limiter.limit decorators on the auth endpoints are untested: deleting one
would leave the whole suite green.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db, limiter


@pytest.fixture()
def limited_client(tmp_path):
    class RateLimitedConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/test.db"
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = True
        RATELIMIT_STORAGE_URI = "memory://"
        PROXY_HOPS = 0
        WORKER_ENABLED = False

    app = create_app(RateLimitedConfig)
    yield app.test_client()
    # `limiter` is a module-level singleton: clear its counters so no hits
    # carry into a later test that also enables it.
    limiter.reset()
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_login_rate_limit_returns_429_after_ten_attempts(limited_client):
    # login is "10 per minute": ten bad attempts are answered normally...
    for i in range(10):
        r = limited_client.post(
            "/api/v1/users/login",
            json={"username": "nobody@example.com", "password": f"wrong-{i}"},
        )
        assert r.status_code != 429, f"attempt {i + 1} was rate limited early"
    # ...and the eleventh is refused by the limiter.
    r = limited_client.post(
        "/api/v1/users/login",
        json={"username": "nobody@example.com", "password": "wrong-final"},
    )
    assert r.status_code == 429


def test_register_rate_limit_returns_429_after_five_attempts(limited_client):
    # register is "5 per minute".
    for i in range(5):
        r = limited_client.post(
            "/api/v1/users/register",
            json={"email": f"u{i}@example.com", "password": "password", "name": "U"},
        )
        assert r.status_code != 429, f"attempt {i + 1} was rate limited early"
    r = limited_client.post(
        "/api/v1/users/register",
        json={"email": "u-final@example.com", "password": "password", "name": "U"},
    )
    assert r.status_code == 429
