"""Behind HA ingress each HA user gets a distinct identity (from X-Remote-User-*),
all sharing one household; first user = owner. Trust boundary: headers honored
ONLY from the Supervisor peer (172.30.32.2) — a forged header from a directly
published port must never impersonate."""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db

INGRESS = {"REMOTE_ADDR": "172.30.32.2"}


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


@pytest.fixture()
def ic(iapp):
    return iapp.test_client()


def _me(c, ha=None, name=None, ingress=True):
    headers = {}
    if ha:
        headers["X-Remote-User-Id"] = ha
    if name:
        headers["X-Remote-User-Display-Name"] = name
    kw = {"headers": headers}
    if ingress:
        kw["environ_overrides"] = INGRESS
    return c.get("/api/v1/me", **kw).get_json()


def test_ingress_provisions_distinct_users_first_is_owner(ic):
    a = _me(ic, "alice", "Alice")
    assert a["name"] == "Alice" and a["isOwner"] is True and a["ha"] is True
    b = _me(ic, "bob", "Bob")
    assert b["isOwner"] is False and b["ha"] is True and b["id"] != a["id"]
    assert _me(ic, "alice")["id"] == a["id"]


def test_forged_header_from_non_ingress_peer_is_ignored(ic):
    a = _me(ic, "attacker", "Mallory", ingress=False)
    assert a["ha"] is False and a["isOwner"] is True   # shared local user
    b = _me(ic, "someone-else", "Eve", ingress=False)
    assert b["id"] == a["id"]                            # never per-header


def test_member_403s_on_owner_tokens_owner_ok(ic):
    _me(ic, "owner1", "Owner")
    member = ic.post("/api/v1/tokens", json={"name": "k"},
                     headers={"X-Remote-User-Id": "member1"}, environ_overrides=INGRESS)
    assert member.status_code == 403
    owner = ic.post("/api/v1/tokens", json={"name": "k"},
                    headers={"X-Remote-User-Id": "owner1"}, environ_overrides=INGRESS)
    assert owner.status_code in (200, 201)


def test_migration_backfills_ownerless_admin(app):
    from app import _migrate
    from app.models import User, Group
    with app.app_context():
        g = Group(name="H")
        db.session.add(g)
        db.session.flush()
        u = User(name="Alex", email="alex@x.com", password_hash="x",
                 is_owner=False, group_id=g.id)
        db.session.add(u)
        db.session.commit()
        _migrate(app)
        db.session.refresh(u)
        assert u.is_owner is True


def test_member_403s_on_group_config(ic):
    _me(ic, "owner1", "Owner")
    hdr = {"X-Remote-User-Id": "member1"}
    assert ic.put("/api/v1/groups", json={"currency": "eur"},
                  headers=hdr, environ_overrides=INGRESS).status_code == 403
    assert ic.post("/api/v1/groups/invitations", json={"uses": 1},
                   headers=hdr, environ_overrides=INGRESS).status_code == 403
    assert ic.put("/api/v1/groups", json={"currency": "eur"},
                  headers={"X-Remote-User-Id": "owner1"},
                  environ_overrides=INGRESS).status_code == 200
