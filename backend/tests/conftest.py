import pytest

from app import create_app
from app.config import Config
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/test.db"
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0
        WORKER_ENABLED = False  # tests drive job functions directly, no poller thread

    app = create_app(TestConfig)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    client.post(
        "/api/v1/users/register",
        json={"email": "t@t.com", "password": "password", "name": "T"},
    )
    token = client.post(
        "/api/v1/users/login", json={"username": "t@t.com", "password": "password"}
    ).get_json()["token"]
    client.environ_base["HTTP_AUTHORIZATION"] = token
    return client


@pytest.fixture()
def noauth_app(tmp_path):
    class NoAuthConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/test.db"
        DISABLE_AUTH = True
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0

    return create_app(NoAuthConfig)


@pytest.fixture()
def gid(app, auth_client):
    """The group the authenticated test client is acting as.

    Resolved through the USER, deliberately: the hand-rolled copies came in two
    flavours — `User(email=...).group_id` and `Group.first().id` — which agree
    only while a test has exactly one household. Once a test registers a second,
    `Group.first()` returns whichever row the DB hands back first, so a
    cross-tenant assertion can quietly check the wrong household."""
    from app.models import User
    with app.app_context():
        return db.session.query(User).filter_by(
            email="t@t.com").first().group_id
