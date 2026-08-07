"""MCP transport auth for external exposure — the DB-backed, scoped key guard.

The MCP sidecar validates a presented bearer against the ApiToken store (scope
mcp/full) and, when mcp_expose_external is on, refuses to serve unless an mcp-scoped
key exists. These test the guard functions directly (no uvicorn / network).
"""
import asyncio
import json

import pytest

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


def _drive_guard(headers, external=True):
    """Run the real _guard against a passthrough ASGI app; return sent messages.

    Drives _guard, not the old _guard_external: that wrapper is gone, and a test
    exercising a code path the server no longer installs proves nothing.
    """
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    _prev = mcp_server._expose_external
    mcp_server._expose_external = lambda: external
    try:
        guard = mcp_server._guard(downstream, "")
    finally:
        mcp_server._expose_external = _prev
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

def _drive(headers, method="GET", path="/sse", body=b"", external=True,
           server_token=""):
    """Drive the real _guard with a method/path/body so tool gating runs."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    _prev = mcp_server._expose_external
    mcp_server._expose_external = lambda: external
    try:
        guard = mcp_server._guard(downstream, server_token)
    finally:
        mcp_server._expose_external = _prev
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


def test_read_only_key_blocks_write_on_the_internal_token_path(app, auth_client, monkeypatch):
    """A key's access is a property of the KEY, not the exposure. Mapping the
    MCP port to the LAN + setting a server token (expose_external off) must not
    grant a read-only key write — the read/write check used to live inside
    `if external:`."""
    monkeypatch.setattr(mcp_server, "_app", app)
    ro = _mint(auth_client, "mcp", "read")
    hdr = [(b"authorization", f"Bearer {ro}".encode())]
    assert _drive(hdr, "POST", "/messages/", _call("add_item_placement"),
                  external=False, server_token="tok")[0]["status"] == 403
    # write tool still writes for a write key on the same path
    rw = _mint(auth_client, "mcp", "write")
    hdrw = [(b"authorization", f"Bearer {rw}".encode())]
    assert _drive(hdrw, "POST", "/messages/", _call("add_item_placement"),
                  external=False, server_token="tok")[0]["status"] == 200


def test_read_only_key_blocks_write_on_the_open_internal_path(app, auth_client, monkeypatch):
    """Even with no server token (HA zero-setup), a presented read-only key is
    still read-only."""
    monkeypatch.setattr(mcp_server, "_app", app)
    ro = _mint(auth_client, "mcp", "read")
    hdr = [(b"authorization", f"Bearer {ro}".encode())]
    assert _drive(hdr, "POST", "/messages/", _call("add_item_placement"),
                  external=False, server_token="")[0]["status"] == 403


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


# ---- The debug scope --------------------------------------------------------
#
# A debug key reads this instance's own logs, which carry login emails and
# tracebacks that can include a database password. It is therefore a separate
# key class, denied at REST and denied on the domain tools — and the debug tools
# are denied to every other key, on every network.

def _call(tool):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool}}).encode()


def test_a_debug_key_is_rejected_at_the_rest_api(app, auth_client, client):
    debug_raw = _mint(auth_client, "debug")

    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {debug_raw}"

    assert client.get("/api/v1/items").status_code == 401


def test_a_debug_key_may_call_a_debug_tool(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    debug_raw = _mint(auth_client, "debug")

    sent = _drive([(b"authorization", f"Bearer {debug_raw}".encode())],
                  method="POST", path="/messages", body=_call("debug_recent_logs"),
                  external=False)

    assert sent[0]["status"] == 200


def test_a_debug_key_may_not_call_a_domain_tool(app, auth_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "_app", app)
    debug_raw = _mint(auth_client, "debug")

    sent = _drive([(b"authorization", f"Bearer {debug_raw}".encode())],
                  method="POST", path="/messages", body=_call("where_is"),
                  external=False)

    assert sent[0]["status"] == 403


@pytest.mark.parametrize("scope", ["full", "mcp"])
def test_a_normal_key_may_not_call_a_debug_tool(app, auth_client, monkeypatch, scope):
    """Least privilege in both directions — otherwise the 'debug only' label is
    a lie and any Assist key could read the logs."""
    monkeypatch.setattr(mcp_server, "_app", app)
    raw = _mint(auth_client, scope)

    sent = _drive([(b"authorization", f"Bearer {raw}".encode())],
                  method="POST", path="/messages", body=_call("debug_recent_logs"),
                  external=False)

    assert sent[0]["status"] == 403


def test_an_unauthenticated_caller_may_not_call_a_debug_tool_even_internally(app, monkeypatch):
    """The case that motivated always installing the guard: with external
    exposure off, HomeHoard previously installed NO guard at all, so this
    request would have reached the tool with no credential."""
    monkeypatch.setattr(mcp_server, "_app", app)

    sent = _drive([], method="POST", path="/messages",
                  body=_call("debug_recent_logs"), external=False)

    assert sent[0]["status"] == 403


def test_domain_tools_stay_open_internally(app, monkeypatch):
    """Voice control must keep working without setup on the HA network."""
    monkeypatch.setattr(mcp_server, "_app", app)

    sent = _drive([], method="POST", path="/messages",
                  body=_call("where_is"), external=False)

    assert sent[0]["status"] == 200


def test_a_batch_cannot_smuggle_a_domain_tool_past_a_debug_key(app, auth_client, monkeypatch):
    """JSON-RPC batches are checked element-wise: pairing a debug tool with a
    domain tool must not let the domain one through."""
    monkeypatch.setattr(mcp_server, "_app", app)
    debug_raw = _mint(auth_client, "debug")
    batch = json.dumps([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "debug_recent_logs"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "create_item"}},
    ]).encode()

    sent = _drive([(b"authorization", f"Bearer {debug_raw}".encode())],
                  method="POST", path="/messages", body=batch, external=False)

    assert sent[0]["status"] == 403


def test_debug_scope_is_accepted_by_the_tokens_api(auth_client):
    r = auth_client.post("/api/v1/tokens",
                         json={"name": "d", "scope": "debug", "access": "read"})

    assert r.status_code in (200, 201)
    assert r.get_json()["scope"] == "debug"


# ---- The method-bypass blocker ---------------------------------------------
#
# FastMCP mounts the message endpoint with Starlette's Mount, which matches on
# PATH ONLY, and handle_post_message never checks the method either — so PUT,
# GET and DELETE are processed exactly like POST. Gating the guard on
# method == "POST" meant it saw no tool names and applied no rule at all: an
# unauthenticated caller could open /sse (open by design on the HA network),
# take the session id, and PUT a tools/call for a debug tool.

@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE", "PATCH"])
def test_a_debug_tool_cannot_be_reached_with_a_non_post_method(app, monkeypatch, method):
    monkeypatch.setattr(mcp_server, "_app", app)

    sent = _drive([], method=method, path="/messages/",
                  body=_call("debug_recent_logs"), external=False)

    assert sent[0]["status"] == 403


@pytest.mark.parametrize("method", ["PUT", "GET"])
def test_a_debug_key_cannot_reach_a_domain_tool_with_a_non_post_method(
        app, auth_client, monkeypatch, method):
    monkeypatch.setattr(mcp_server, "_app", app)
    debug_raw = _mint(auth_client, "debug")

    sent = _drive([(b"authorization", f"Bearer {debug_raw}".encode())],
                  method=method, path="/messages/", body=_call("where_is"),
                  external=False)

    assert sent[0]["status"] == 403


def test_a_read_only_key_cannot_write_with_a_non_post_method(app, auth_client, monkeypatch):
    """Pre-existing hole in the read-only gate, which was also POST-only."""
    monkeypatch.setattr(mcp_server, "_app", app)
    read_raw = _mint(auth_client, "mcp", access="read")

    sent = _drive([(b"authorization", f"Bearer {read_raw}".encode())],
                  method="PUT", path="/messages/", body=_call("create_item"),
                  external=True)

    assert sent[0]["status"] == 403


def test_a_malformed_params_list_does_not_500(app, monkeypatch):
    """`params` may legitimately be a list; .get on it raised, turning an
    unauthenticated request into a 500."""
    monkeypatch.setattr(mcp_server, "_app", app)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": []}).encode()

    sent = _drive([], method="POST", path="/messages/", body=body, external=False)

    assert sent[0]["status"] in (200, 401, 403)
