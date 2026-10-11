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


# --- identity keying (_limiter_key) ----------------------------------------

def _login(client, email, headers=None, n=1):
    last = None
    for i in range(n):
        last = client.post(
            "/api/v1/users/login",
            json={"username": email, "password": f"wrong-{i}"},
            headers=headers or {},
        )
    return last


def test_login_buckets_are_per_email_not_per_address(limited_client):
    # Exhaust one account's bucket from this address...
    assert _login(limited_client, "a@example.com", n=10).status_code != 429
    assert _login(limited_client, "a@example.com").status_code == 429
    # ...another account behind the same address is unaffected.
    assert _login(limited_client, "b@example.com").status_code != 429


def test_login_email_is_normalised_into_one_bucket(limited_client):
    assert _login(limited_client, "a@example.com", n=10).status_code != 429
    assert _login(limited_client, "  A@Example.COM ").status_code == 429


def test_login_ignores_forged_authorization_header(limited_client):
    # Authorization is unauthenticated input on login: rotating it must not
    # mint a fresh bucket.
    for i in range(10):
        _login(limited_client, "a@example.com", headers={"Authorization": f"Bearer x{i}"})
    r = _login(limited_client, "a@example.com", headers={"Authorization": "Bearer fresh"})
    assert r.status_code == 429


def test_register_bucket_is_per_address_not_per_email(limited_client):
    for i in range(5):
        r = limited_client.post(
            "/api/v1/users/register",
            json={"email": f"v{i}@example.com", "password": "password", "name": "U"},
            headers={"Authorization": f"Bearer x{i}"},
        )
        assert r.status_code != 429
    r = limited_client.post(
        "/api/v1/users/register",
        json={"email": "v-final@example.com", "password": "password", "name": "U"},
    )
    assert r.status_code == 429


def test_limiter_key_uses_credential_when_present(limited_client):
    from app.extensions import _limiter_key

    app = limited_client.application
    def key(headers):
        with app.test_request_context("/api/v1/items", headers=headers,
                                      environ_base={"REMOTE_ADDR": "10.0.0.1"}):
            return _limiter_key()

    assert key({"Authorization": "Bearer one"}) == key({"Authorization": "Bearer one"})
    assert key({"Authorization": "Bearer one"}) != key({"Authorization": "Bearer two"})
    assert key({}) == "10.0.0.1"
    assert "Bearer one" not in key({"Authorization": "Bearer one"})


def test_two_tokens_from_one_address_do_not_share_a_bucket(limited_client):
    # Real limiter on a real endpoint: /users/refresh is not limited, so use
    # the registered limit scope directly through a throwaway route.
    from flask import jsonify
    from app.extensions import limiter

    app = limited_client.application

    @app.route("/_t/limited")
    @limiter.limit("3 per minute")
    def _limited():
        return jsonify(ok=True)

    def hit(tok):
        return limited_client.get("/_t/limited", headers={"Authorization": f"Bearer {tok}"})

    for _ in range(3):
        assert hit("A").status_code == 200
    assert hit("A").status_code == 429          # same token: shared bucket
    assert hit("B").status_code == 200          # other token, same IP: own bucket


def test_limiter_key_never_raises_on_bad_body(limited_client):
    from app.extensions import _limiter_key

    app = limited_client.application
    with app.test_request_context("/api/v1/users/login", method="POST",
                                  data=b"\xff\xfe not json",
                                  content_type="application/json"):
        assert _limiter_key()   # falls back to the IP, no exception


def test_proxy_hops_option_round_trips_through_the_settings_adapter():
    from app.settings import load_settings

    s = load_settings(env={}, ha_options={"proxy_hops": 2, "disable_auth": False},
                      validate=False)
    assert s.PROXY_HOPS == 2
    # env still works, and a HA option outranks it (documented precedence).
    s = load_settings(env={"HBOX_PROXY_HOPS": "1"}, ha_options={"proxy_hops": 3},
                      validate=False)
    assert s.PROXY_HOPS == 3


def test_login_spraying_across_emails_is_capped_per_address(limited_client):
    # Per-email buckets alone would let one address try 10 passwords against
    # every account; the second, address-keyed limit stops that at 40/min.
    for i in range(40):
        assert _login(limited_client, f"u{i}@example.com").status_code != 429
    assert _login(limited_client, "u99@example.com").status_code == 429


def _register_and_login(c, email="v@v.com"):
    c.post("/api/v1/users/register",
           json={"email": email, "password": "password", "name": "V"})
    tok = c.post("/api/v1/users/login",
                 json={"username": email, "password": "password"}).get_json()["token"]
    return tok.split(" ", 1)[-1]  # login returns "Bearer <jwt>"; keep the bare jwt


# P109/B1: one credential, many spellings. auth._bearer_token accepts any scheme
# case and inner whitespace, so the bucket key must too.
_SPELLINGS = ["Bearer {}", "bearer {}", "BEARER {}", "Bearer  {}", " Bearer {} ",
              "bEaReR   {}", "{}", "Bearer {}\t", "bearer  {} ",
              "Bearer   {}  ", "BeArEr {}"]


def test_limiter_key_ignores_authorization_spelling(limited_client):
    from app.extensions import _limiter_key

    app = limited_client.application
    keys = set()
    for spelling in _SPELLINGS:
        with app.test_request_context("/api/v1/vault/unlock",
                                      headers={"Authorization": spelling.format("tok")},
                                      environ_base={"REMOTE_ADDR": "10.0.0.1"}):
            keys.add(_limiter_key())
    assert len(keys) == 1, keys


def test_header_spelling_rotation_does_not_mint_buckets(limited_client):
    # /vault/passphrase: 10/hour on the credential key, and no per-user bucket
    # to mask a regression in the key itself.
    tok = _register_and_login(limited_client)
    codes = [
        limited_client.post("/api/v1/vault/passphrase", json={"phrase": "x"},
                            headers={"Authorization": s.format(tok)}).status_code
        for s in _SPELLINGS
    ]
    assert 429 not in codes[:10], codes
    assert codes[10] == 429, codes


# P109/SF1: every login is a fresh JWT = a fresh credential bucket, so unlock
# also draws from a bucket keyed on the authenticated user.
def test_unlock_user_bucket_is_shared_across_logins(limited_client):
    import time

    tok_a = _register_and_login(limited_client)
    time.sleep(1.1)  # a second login in the same second can mint the same JWT
    tok_b = limited_client.post("/api/v1/users/login", json={
        "username": "v@v.com", "password": "password"}).get_json()["token"]
    tok_b = tok_b.split(" ", 1)[-1]
    assert tok_a != tok_b
    assert limited_client.post("/api/v1/vault/passphrase", json={"phrase": "right"},
                               headers={"Authorization": f"Bearer {tok_a}"}).status_code == 200

    def unlock(tok, phrase="wrong"):
        return limited_client.post("/api/v1/vault/unlock", json={"phrase": phrase},
                                   headers={"Authorization": f"Bearer {tok}"}).status_code

    assert [unlock(tok_a) for _ in range(5)] == [403] * 5
    assert [unlock(tok_b) for _ in range(5)] == [403] * 5
    # B's credential bucket has 5 left; only the user bucket can refuse this.
    assert unlock(tok_b, "right") == 429
