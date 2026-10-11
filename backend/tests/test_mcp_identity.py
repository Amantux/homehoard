"""P31: the MCP sidecar's REST calls act as the MCP CALLER, not the shared household.

The sidecar authenticates to REST with the integration token and relays the
caller's own key in ``X-HBOX-Acting-Key``. REST honours that header only
alongside THE integration token, re-verifies the acting key, and fails closed
(401) on anything else — never a fallback to the integration token's identity.
"""
import json
import types

import pytest

import mcp_server
from app.auth import ACTING_KEY_HEADER
from app.integration_token import ensure_integration_token


def _user(app, email):
    """A fresh registered user (own household) → a JWT-authenticated client."""
    c = app.test_client()
    c.post("/api/v1/users/register",
           json={"email": email, "password": "password", "name": email})
    tok = c.post("/api/v1/users/login",
                 json={"username": email, "password": "password"}).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = tok  # login returns it scheme-included, as conftest uses it
    return c


def _mint(c, scope="mcp", access="write", name=None):
    return c.post("/api/v1/tokens", json={
        "name": name or scope, "scope": scope, "access": access,
    }).get_json()["token"]


@pytest.fixture()
def world(app):
    a, b = _user(app, "a@a.com"), _user(app, "b@b.com")
    assert a.post("/api/v1/items", json={"name": "Alpha drill"}).status_code == 201
    assert b.post("/api/v1/items", json={"name": "Bravo saw"}).status_code == 201
    integ = ensure_integration_token(app)
    assert integ
    return types.SimpleNamespace(
        a=a, b=b, integ=integ,
        key_a=_mint(a), key_b=_mint(b), key_b_ro=_mint(b, access="read"),
    )


def _call(app, method, path, bearer, acting=None, **kw):
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    if acting is not None:
        headers[ACTING_KEY_HEADER] = acting
    return getattr(app.test_client(), method)(path, headers=headers, **kw)


def test_a_integration_token_with_acting_key_sees_only_that_users_items(app, world):
    r = _call(app, "get", "/api/v1/items", world.integ, acting=world.key_b)
    assert r.status_code == 200
    body = json.dumps(r.get_json())
    assert "Bravo saw" in body
    assert "Alpha drill" not in body
    # And the other way round — attribution follows the acting key, not a cache.
    r = _call(app, "get", "/api/v1/items", world.integ, acting=world.key_a)
    body = json.dumps(r.get_json())
    assert "Alpha drill" in body and "Bravo saw" not in body


def test_b_read_only_acting_key_cannot_write(app, world):
    r = _call(app, "post", "/api/v1/items", world.integ, acting=world.key_b_ro,
              json={"name": "Nope"})
    assert r.status_code == 403
    # Control: the same POST with the write key succeeds.
    r = _call(app, "post", "/api/v1/items", world.integ, acting=world.key_b,
              json={"name": "Yes"})
    assert r.status_code == 201


@pytest.mark.parametrize("acting", ["hh_not_a_real_key", "", "garbage"])
def test_c_bogus_acting_key_is_401_not_a_fallback(app, world, acting):
    r = _call(app, "get", "/api/v1/items", world.integ, acting=acting)
    assert r.status_code == 401


def test_c_rest_scoped_acting_key_is_401(app, world):
    # A rest-only key never reaches MCP, so it can't be relayed from there either.
    r = _call(app, "get", "/api/v1/items", world.integ, acting=_mint(world.b, "rest"))
    assert r.status_code == 401


def test_d_acting_header_with_any_other_bearer_is_401(app, world):
    full_b = _mint(world.b, "full")
    # A user-minted key that merely borrows the integration token's NAME.
    spoof = _mint(world.a, "full", name="Home Assistant integration")
    jwt = world.a.environ_base["HTTP_AUTHORIZATION"].removeprefix("Bearer ")
    for bearer in (full_b, spoof, jwt):
        r = _call(app, "get", "/api/v1/items", bearer, acting=world.key_b)
        assert r.status_code == 401, bearer[:9]
    # No Bearer at all → 401 too, never ingress/open-mode.
    assert _call(app, "get", "/api/v1/items", None, acting=world.key_b).status_code == 401
    # Controls: the same Bearers WITHOUT the header still work.
    assert _call(app, "get", "/api/v1/items", full_b).status_code == 200
    assert _call(app, "get", "/api/v1/items", spoof).status_code == 200


def test_integration_token_without_header_is_unchanged(app, world):
    # The HA integration's own REST traffic never sends the header.
    assert _call(app, "get", "/api/v1/items", world.integ).status_code == 200


# ---- (e) the sidecar side: _caller_headers reads the POST request's key ----

def _fake_ctx(monkeypatch, request):
    rc = types.SimpleNamespace(request=request)
    monkeypatch.setattr(mcp_server.mcp, "get_context",
                        lambda: types.SimpleNamespace(request_context=rc))


def _req(auth):
    return types.SimpleNamespace(headers={"authorization": auth} if auth else {})


def test_e_caller_headers_relays_the_presented_key(monkeypatch):
    monkeypatch.setattr(mcp_server, "_BARE_TOKEN", "hh_integration")
    _fake_ctx(monkeypatch, _req("Bearer hh_callerkey"))
    assert mcp_server._caller_headers() == {ACTING_KEY_HEADER: "hh_callerkey"}


@pytest.mark.parametrize("auth", [None, "Bearer s3cr3t-static", "Basic hh_x"])
def test_e_caller_headers_empty_without_a_presented_api_key(monkeypatch, auth):
    monkeypatch.setattr(mcp_server, "_BARE_TOKEN", "hh_integration")
    _fake_ctx(monkeypatch, _req(auth))
    assert mcp_server._caller_headers() == {}


def test_e_caller_headers_empty_outside_a_request(monkeypatch):
    monkeypatch.setattr(mcp_server, "_BARE_TOKEN", "hh_integration")
    assert mcp_server._caller_headers() == {}  # real SDK: no request context


def test_e_caller_headers_empty_when_sidecar_has_no_token(monkeypatch):
    monkeypatch.setattr(mcp_server, "_BARE_TOKEN", "")
    _fake_ctx(monkeypatch, _req("Bearer hh_callerkey"))
    assert mcp_server._caller_headers() == {}


def test_guard_does_one_key_lookup_per_request(app, world, monkeypatch):
    """B12: the guard's three lookups collapse into one, run off the event loop."""
    import asyncio
    calls = []
    real = mcp_server._key_record
    monkeypatch.setattr(mcp_server, "_app", app)
    monkeypatch.setattr(mcp_server, "_key_record", lambda raw: calls.append(raw) or real(raw))
    monkeypatch.setattr(mcp_server, "_expose_external", lambda: True)
    monkeypatch.setattr(mcp_server, "_require_key", lambda: True)

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "search_inventory", "arguments": {}}}).encode()
    scope = {"type": "http", "method": "POST", "path": "/messages/", "query_string": b"",
             "headers": [(b"authorization", f"Bearer {world.key_b}".encode())]}
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mcp_server._guard(downstream, "")(scope, receive, send))
    assert sent[0]["status"] == 200
    assert calls == [world.key_b]


# --- P71c: expired API keys are rejected on the MCP transport ----------------

def _set_expiry(app, raw, delta):
    from app.extensions import db
    from app.models import ApiToken, hash_token
    from app.timeutil import utcnow
    with app.app_context():
        rec = db.session.query(ApiToken).filter_by(token_hash=hash_token(raw)).first()
        rec.expires_at = None if delta is None else (utcnow() + delta).replace(tzinfo=None)
        db.session.commit()


def test_expired_key_is_rejected_like_an_unknown_key(app, world, monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(mcp_server, "_app", app)
    assert mcp_server._key_record(world.key_a) is not None
    _set_expiry(app, world.key_a, timedelta(seconds=-60))
    assert mcp_server._key_record(world.key_a) is None
    assert mcp_server._key_record("hh_not_a_real_key") is None
    assert mcp_server._key_ok(world.key_a) is False


def test_future_expiry_key_is_accepted(app, world, monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(mcp_server, "_app", app)
    _set_expiry(app, world.key_a, timedelta(days=1))
    assert mcp_server._key_record(world.key_a) == ("mcp", "write")


def test_null_expiry_key_is_accepted(app, world, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    _set_expiry(app, world.key_a, None)
    assert mcp_server._key_record(world.key_a) == ("mcp", "write")
