"""A group must never be left with zero owners via self-delete.

delete_self deleted the caller unconditionally. The sole owner deleting
themselves stranded the remaining members with a 403 on every owner-gated
surface (tokens, notifiers, AI config) and no runtime recovery — the
owner-backfill only runs for a pre-Alembic DB at boot.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db

INGRESS = {"REMOTE_ADDR": "172.30.32.2"}


@pytest.fixture()
def iapp(tmp_path):
    class C(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/sd.db"
        DISABLE_AUTH = True
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0
    app = create_app(C)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _touch(c, ha):
    """Provision/refresh the HA user (first becomes owner)."""
    return c.get("/api/v1/me", headers={"X-Remote-User-Id": ha},
                 environ_overrides=INGRESS)


def _del(c, ha):
    return c.delete("/api/v1/users/self",
                    headers={"X-Remote-User-Id": ha}, environ_overrides=INGRESS)


def test_the_last_owner_cannot_self_delete(iapp):
    c = iapp.test_client()
    _touch(c, "owner1")     # first HA user -> owner
    _touch(c, "member1")    # second -> member

    r = _del(c, "owner1")
    assert r.status_code == 409, "the last owner was allowed to delete themselves"


def test_a_member_can_self_delete(iapp):
    c = iapp.test_client()
    _touch(c, "owner1")
    _touch(c, "member1")

    assert _del(c, "member1").status_code == 204


def test_an_owner_can_self_delete_when_another_owner_remains(iapp):
    c = iapp.test_client()
    _touch(c, "owner1")
    _touch(c, "member1")
    # promote member1 to owner
    from app.models import User
    with iapp.app_context():
        m = db.session.query(User).filter_by(ha_user_id="member1").first()
        m.is_owner = True
        db.session.commit()

    assert _del(c, "owner1").status_code == 204
