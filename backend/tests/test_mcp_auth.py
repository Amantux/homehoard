"""MCP transport auth for external exposure — the DB-backed, scoped key guard.

The MCP sidecar validates a presented bearer against the ApiToken store (scope
mcp/full) and, when mcp_expose_external is on, refuses to serve unless an mcp-scoped
key exists. These test the guard functions directly (no uvicorn / network).
"""
import asyncio

import mcp_server


def _mint(auth_client, scope):
    return auth_client.post(
        "/api/v1/tokens", json={"name": scope, "scope": scope}
    ).get_json()["token"]


def test_key_ok_accepts_mcp_and_full_rejects_rest_and_junk(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)  # use the test DB, not a fresh app
    mcp_raw = _mint(auth_client, "mcp")
    full_raw = _mint(auth_client, "full")
    rest_raw = _mint(auth_client, "rest")
    assert mcp_server._key_ok(mcp_raw) is True
    assert mcp_server._key_ok(full_raw) is True
    assert mcp_server._key_ok(rest_raw) is False   # rest scope can't reach MCP
    assert mcp_server._key_ok("hh_not_a_real_token") is False
    assert mcp_server._key_ok("") is False


def test_mcp_key_exists_counts_any_usable_key(app, auth_client, monkeypatch):
    # refuse-to-serve asks "is there a usable credential?" — a Full key authenticates
    # every request (docs say "mint an MCP or Full key"), so it counts; a rest key does not.
    monkeypatch.setattr(mcp_server, "_app", app)
    assert mcp_server._mcp_key_exists() is False
    _mint(auth_client, "rest")   # rest-only can't reach MCP → still no usable key
    assert mcp_server._mcp_key_exists() is False
    _mint(auth_client, "full")   # a full key is usable → counts
    assert mcp_server._mcp_key_exists() is True


def test_authorized_bearer_and_static_token(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    mcp_raw = _mint(auth_client, "mcp")
    rest_raw = _mint(auth_client, "rest")
    assert mcp_server._authorized(f"Bearer {mcp_raw}", "") is True
    assert mcp_server._authorized(f"Bearer {rest_raw}", "") is False
    assert mcp_server._authorized("", "") is False
    # A static server token, if configured, is also accepted (constant-time).
    assert mcp_server._authorized("Bearer s3cr3t", "s3cr3t") is True
    assert mcp_server._authorized("Bearer wrong", "s3cr3t") is False


def _drive_guard(headers):
    """Run _guard_external against a passthrough ASGI app; return the sent messages."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = mcp_server._guard_external(downstream, "")
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "headers": headers}
    asyncio.run(guard(scope, receive, send))
    return sent


def test_guard_blocks_without_key_and_passes_with_mcp_key(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    mcp_raw = _mint(auth_client, "mcp")

    no_auth = _drive_guard([])
    assert no_auth[0]["status"] == 401

    bad = _drive_guard([(b"authorization", b"Bearer hh_bogus")])
    assert bad[0]["status"] == 401

    ok = _drive_guard([(b"authorization", f"Bearer {mcp_raw}".encode())])
    assert ok[0]["status"] == 200
