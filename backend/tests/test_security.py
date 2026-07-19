"""Regression tests for the security remediation batch (see SECURITY-REVIEW.md)."""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db


# --- C1: fail closed on a default signing secret ---------------------------
def test_boot_refuses_default_secret_with_auth(tmp_path):
    class BadConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/b.db"
        DISABLE_AUTH = False
        SECRET_KEY = "change-me-in-production"
        RATELIMIT_ENABLED = False

    with pytest.raises(RuntimeError):
        create_app(BadConfig)


def test_boot_refuses_weak_custom_secret(tmp_path):
    class WeakConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/w.db"
        DISABLE_AUTH = False
        SECRET_KEY = "tooshort"  # not a known default, but < 32 chars
        RATELIMIT_ENABLED = False

    with pytest.raises(RuntimeError):
        create_app(WeakConfig)


def test_default_secret_allowed_when_auth_disabled(tmp_path):
    class NoAuthDefault(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/n.db"
        DISABLE_AUTH = True
        SECRET_KEY = "change-me-in-production"
        RATELIMIT_ENABLED = False

    app = create_app(NoAuthDefault)  # must not raise
    assert app is not None
    with app.app_context():
        db.drop_all()


# --- M1: security headers --------------------------------------------------
def test_security_headers_present(client):
    r = client.get("/api/v1/status")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    # auth enabled in the test app -> clickjacking protection asserted
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


# --- L2: password policy ---------------------------------------------------
def test_register_rejects_short_password(client):
    r = client.post("/api/v1/users/register",
                    json={"email": "s@t.com", "password": "short", "name": "S"})
    assert r.status_code == 422


# --- H1: SSRF-safe notifier URLs ------------------------------------------
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://127.0.0.1:8080/",                     # loopback
    "http://10.0.0.5/hook",                        # RFC1918
    "http://[::1]/x",                              # ipv6 loopback
    "ntfy://10.0.0.5/topic",                       # self-hosted provider → internal host
    "mqtt://192.168.1.9",                          # provider scheme, private IP
    "http://2130706433/",                          # decimal-encoded 127.0.0.1
])
def test_notifier_blocks_internal_urls(auth_client, url):
    r = auth_client.post("/api/v1/notifiers", json={"name": "x", "url": url})
    assert r.status_code == 422


def test_notifier_allows_public_and_provider_urls(auth_client):
    # A provider scheme (fixed endpoint) is allowed without DNS resolution.
    r = auth_client.post("/api/v1/notifiers",
                         json={"name": "tg", "url": "tgram://token/chatid"})
    assert r.status_code == 201


# --- L1: notifier is user-scoped (not just group) --------------------------
def test_notifier_not_visible_or_editable_cross_user(app, auth_client):
    created = auth_client.post(
        "/api/v1/notifiers", json={"name": "mine", "url": "tgram://a/b"}
    ).get_json()
    # Second user in the SAME group via an invitation.
    inv = auth_client.post("/api/v1/groups/invitations", json={"uses": 5}).get_json()
    peer = app.test_client()
    peer.post("/api/v1/users/register",
              json={"email": "peer@t.com", "password": "password", "name": "P",
                    "token": inv["token"]})
    tok = peer.post("/api/v1/users/login",
                    json={"username": "peer@t.com", "password": "password"}).get_json()["token"]
    peer.environ_base["HTTP_AUTHORIZATION"] = tok
    assert peer.get("/api/v1/notifiers").get_json() == []
    assert peer.delete(f"/api/v1/notifiers/{created['id']}").status_code == 404


# --- M6: invitations respect uses --------------------------------------------
def test_invitation_uses_are_consumed(app, auth_client):
    inv = auth_client.post("/api/v1/groups/invitations", json={"uses": 1}).get_json()
    ok = app.test_client().post(
        "/api/v1/users/register",
        json={"email": "u1@t.com", "password": "password", "name": "U1",
              "token": inv["token"]},
    )
    assert ok.status_code == 201
    # Second use of a 1-use invitation is rejected.
    again = app.test_client().post(
        "/api/v1/users/register",
        json={"email": "u2@t.com", "password": "password", "name": "U2",
              "token": inv["token"]},
    )
    assert again.status_code == 422


# --- M5: pagination is clamped, never "all" --------------------------------
def test_pagesize_zero_does_not_dump_everything(auth_client):
    for n in range(3):
        auth_client.post("/api/v1/items", json={"name": f"i{n}"})
    r = auth_client.get("/api/v1/items?pageSize=0").get_json()
    assert r["pageSize"] >= 1  # clamped, not 0/unbounded
    # Non-numeric input must not 500.
    assert auth_client.get("/api/v1/items?pageSize=abc&page=xyz").status_code == 200


# --- M4: CSV export neutralizes formulas -----------------------------------
def test_csv_export_neutralizes_formula(auth_client):
    auth_client.post("/api/v1/items", json={"name": "=1+2"})
    body = auth_client.get("/api/v1/items/export").get_data(as_text=True)
    assert "'=1+2" in body      # prefixed with a quote
    assert "\n=1+2" not in body  # never a bare formula cell


# --- H3: login is rate limited ---------------------------------------------
def test_login_is_rate_limited(tmp_path):
    class LimitedConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/l.db"
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = True
        PROXY_HOPS = 0

    app = create_app(LimitedConfig)
    c = app.test_client()
    statuses = [
        c.post("/api/v1/users/login",
               json={"username": "x@t.com", "password": "nope"}).status_code
        for _ in range(15)
    ]
    assert 429 in statuses  # the limiter kicks in within the window
    with app.app_context():
        db.drop_all()
