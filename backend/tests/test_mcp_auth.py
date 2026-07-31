"""MCP transport auth for external exposure — the DB-backed, scoped key guard.

The MCP sidecar validates a presented bearer against the ApiToken store (scope
mcp/full) and, when mcp_expose_external is on, refuses to serve unless an mcp-scoped
key exists. These test the guard functions directly (no uvicorn / network).
"""
import asyncio
import json

import mcp_server


def _mint(auth_client, scope, access="write"):
    return auth_client.post(
        "/api/v1/tokens", json={"name": scope, "scope": scope, "access": access}
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


# ---- Read-only access class -------------------------------------------------

def _drive(headers, method="GET", path="/sse", body=b""):
    """Drive _guard_external with a method/path/body so read-only tool gating runs."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = mcp_server._guard_external(downstream, "")
    sent, state = [], {"sent_body": False}

    async def send(m):
        sent.append(m)

    async def receive():
        if not state["sent_body"]:
            state["sent_body"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    scope = {"type": "http", "headers": headers, "method": method, "path": path}
    asyncio.run(guard(scope, receive, send))
    return sent


def _call(name):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": {}}}).encode()


def test_key_access_reflects_the_access_class(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    rw = _mint(auth_client, "mcp", "write")
    ro = _mint(auth_client, "mcp", "read")
    assert mcp_server._key_access(rw) == "write"
    assert mcp_server._key_access(ro) == "read"
    assert mcp_server._key_access(_mint(auth_client, "rest", "write")) is None  # not MCP-capable
    assert mcp_server._key_access("hh_bogus") is None


def test_read_only_key_blocks_write_tools_over_mcp(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    ro = _mint(auth_client, "mcp", "read")
    hdr = [(b"authorization", f"Bearer {ro}".encode())]

    # A mutating tool → 403
    assert _drive(hdr, "POST", "/messages/", _call("add_item_placement"))[0]["status"] == 403
    # An unknown/new tool → 403 (fail-safe allowlist)
    assert _drive(hdr, "POST", "/messages/", _call("some_new_tool"))[0]["status"] == 403
    # A read tool → allowed
    assert _drive(hdr, "POST", "/messages/", _call("where_is"))[0]["status"] == 200
    # tools/list and the SSE stream are always allowed
    listing = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    assert _drive(hdr, "POST", "/messages/", listing)[0]["status"] == 200
    assert _drive(hdr, "GET", "/sse")[0]["status"] == 200


def test_read_write_key_may_call_write_tools(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    rw = _mint(auth_client, "mcp", "write")
    hdr = [(b"authorization", f"Bearer {rw}".encode())]
    assert _drive(hdr, "POST", "/messages/", _call("add_item_placement"))[0]["status"] == 200


def test_read_only_token_blocks_writes_on_rest(app, auth_client):
    write_key = _mint(auth_client, "full", "write")
    read_key = _mint(auth_client, "full", "read")
    c = app.test_client()
    ro = {"Authorization": f"Bearer {read_key}"}
    rw = {"Authorization": f"Bearer {write_key}"}
    assert c.get("/api/v1/tokens", headers=ro).status_code == 200
    assert c.post("/api/v1/tokens", json={"name": "x"}, headers=ro).status_code == 403
    # a read+write key (and the JWT owner via auth_client) can still POST
    assert c.post("/api/v1/tokens", json={"name": "y"}, headers=rw).status_code == 201


def test_bad_access_value_rejected(auth_client):
    r = auth_client.post("/api/v1/tokens", json={"name": "k", "access": "bogus"})
    assert r.status_code == 400
