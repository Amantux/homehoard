import os
import tempfile

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

    return create_app(NoAuthConfig)
