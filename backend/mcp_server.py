"""HomeHoard MCP server — exposes inventory tools to Home Assistant.

Runs in the same container as the app (a lightweight second process) and simply
calls the local HomeHoard REST API. Home Assistant's **MCP Client** integration
connects to the SSE endpoint and can then answer things like "where is my drill?"
or check items in/out via Assist.

Run:  python mcp_server.py    (serves SSE on HBOX_MCP_HOST:HBOX_MCP_PORT/sse)
"""
import hmac
import json
import sys

import httpx
from mcp.server.fastmcp import FastMCP

from app.settings import load_settings

# Resolved through the one registry, not raw os.environ: this is a separate
# process, and the entrypoint no longer translates options.json into the
# environment. Reading env directly is also how this file grew its own boolean
# parser for MCP_EXPOSE_EXTERNAL, which differed from Config._bool.
_SETTINGS = load_settings()

API = _SETTINGS.mcp_api
TOKEN = _SETTINGS.MCP_API_TOKEN or None  # only needed if app auth is enabled
# The app's auth requires the "Bearer " scheme (auth.py rejects a bare token), so
# MCP→app calls fail auth without it whenever disable_auth is off. Tolerate a token
# that already includes the scheme (some operators set it to work around the old
# bare-token bug) so we don't double-prefix into "Bearer Bearer …".
_BARE_TOKEN = TOKEN.removeprefix("Bearer ").strip() if TOKEN else ""
_HEADERS = {"Authorization": f"Bearer {_BARE_TOKEN}"} if _BARE_TOKEN else {}
_HTTP = httpx.Client(base_url=API, headers=_HEADERS, timeout=10)

# The MCP SDK ships DNS-rebinding protection that, by default, rejects any
# request whose Host header isn't localhost (returns 421 "Invalid Host header").
# Home Assistant's MCP Client connects to this add-on by its container hostname
# (e.g. http://<slug>-homehoard:7766/sse), so we must allow non-local hosts.
# This server is only reachable on the trusted Supervisor/LAN network.
_fastmcp_kwargs: dict = {}
try:  # mcp >= ~1.9.4
    from mcp.server.transport_security import TransportSecuritySettings

    _fastmcp_kwargs["transport_security"] = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
except ImportError:  # older SDK without the host check — nothing to relax
    pass

mcp = FastMCP("HomeHoard", **_fastmcp_kwargs)


def _get(path: str, params: dict | None = None):
    r = _HTTP.get(path, params=params)
    r.raise_for_status()
    return r.json()


def _post(path: str, json: dict | None = None):
    r = _HTTP.post(path, json=json or {})
    r.raise_for_status()
    return r.json()


def _patch(path: str, json: dict | None = None):
    r = _HTTP.patch(path, json=json or {})
    r.raise_for_status()
    return r.json()


def _resolve(name_or_id: str, kind: str = "item"):
    """``(match, candidates)`` — resolve a name/id, never guessing.

    Delegates to ``/resolve``, which ranks matches by name, labels, description
    and notes and returns a confidence. A confident hit comes back as
    ``(match, [])``; anything ambiguous comes back as ``(None, candidates)`` so
    the caller asks which was meant instead of acting on a coin-flip. Both this
    server and the Home Assistant integration use that one endpoint, so the
    policy can't drift between them.
    """
    try:
        data = _get("/resolve", {"q": name_or_id, "type": kind})
    except httpx.HTTPStatusError:
        return None, []
    if data.get("confidence") == "high":
        return data.get("match"), []
    return None, data.get("candidates") or []


def _describe_candidate(c: dict) -> str:
    """One candidate as a line a user can actually choose between."""
    bits = [f"{c.get('name')} (id {c.get('id')})"]
    if c.get("where"):
        bits.append(f"in {c['where']}")
    labels = [lbl for lbl in (c.get("labels") or []) if lbl]
    if labels:
        bits.append(f"labels: {', '.join(labels[:4])}")
    if c.get("description"):
        bits.append(str(c["description"]))
    if c.get("matchedOn") and c["matchedOn"] != "name":
        bits.append(f"matched on {c['matchedOn']}")
    return " — ".join(bits)


def _clarify(name_or_id: str, candidates: list[dict], kind: str = "item") -> str:
    """Ask which was meant. Returned INSTEAD of acting, so nothing is changed."""
    listed = "; ".join(_describe_candidate(c) for c in candidates)
    return (f"'{name_or_id}' matches several {kind}s: {listed}. "
            f"Nothing was changed — show these to the user, ask which one they "
            f"mean, then call again with that {kind}'s id.")


def _clarify_dict(name_or_id: str, candidates: list[dict], kind: str = "item") -> dict:
    """The same clarification for tools that return structured data."""
    return {
        "needsClarification": True,
        "question": f"Which {kind} did you mean by '{name_or_id}'?",
        "candidates": candidates,
        "hint": f"Call again with the id of the intended {kind}.",
    }


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def where_is(query: str) -> str:
    """Find where an item, bin, or location is in the home inventory.

    Use for questions like "where is my drill" or "which bin has the passport".
    """
    results = _get("/search", {"q": query}).get("results", [])
    if not results:
        return f"I couldn't find '{query}' in the inventory."
    lines = []
    for r in results[:5]:
        if r["type"] == "item":
            lines.append(f"{r['name']} — {r['where'] or 'unassigned'}")
        elif r["type"] == "bin":
            loc = f" in {r['where']}" if r.get("where") else ""
            lines.append(f"{r['name']} (bin{loc}, {r.get('count', 0)} items)")
        else:
            lines.append(f"{r['name']} (location, {r.get('count', 0)} items)")
    return "\n".join(lines)


@mcp.tool()
def search_inventory(query: str) -> list[dict]:
    """Search items, bins, and locations. Returns structured matches."""
    return _get("/search", {"q": query}).get("results", [])


@mcp.tool()
def get_item(name_or_id: str) -> dict:
    """Get full details for a single item (by name or id)."""
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify_dict(name_or_id, candidates)
    if not item:
        return {"error": f"No item matching '{name_or_id}'."}
    return {
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description"),
        "quantity": item.get("quantity"),
        "location": (item.get("location") or {}).get("name"),
        "bin": (item.get("bin") or {}).get("name"),
        # Where it's stocked, per placement (multi-location quantities).
        "placements": [
            {"where": (h.get("bin") or h.get("location") or {}).get("name") or "unassigned",
             "quantity": h.get("quantity")}
            for h in item.get("holdings", [])
        ],
        "checkedOut": item.get("checkedOut"),
        "checkedOutTo": item.get("checkedOutTo"),
        "manufacturer": item.get("manufacturer"),
        "purchasePrice": item.get("purchasePrice"),
    }


@mcp.tool()
def get_bin_contents(name: str) -> dict:
    """List what's inside a bin (by name)."""
    b, candidates = _resolve(name, "bin")
    if candidates:
        return _clarify_dict(name, candidates, "bin")
    if not b:
        return {"error": f"No bin matching '{name}'."}
    return {"bin": b["name"],
            "items": [{"name": i["name"], "quantity": i.get("quantityHere")}
                      for i in b.get("items", [])]}


@mcp.tool()
def get_location_contents(name: str) -> dict:
    """List items and bins in a location (by name)."""
    loc, candidates = _resolve(name, "location")
    if candidates:
        return _clarify_dict(name, candidates, "location")
    if not loc:
        return {"error": f"No location matching '{name}'."}
    return {
        "location": loc["name"],
        "items": [{"name": i["name"], "quantity": i.get("quantityHere")}
                  for i in loc.get("items", [])],
        "bins": [b["name"] for b in loc.get("bins", [])],
    }


@mcp.tool()
def add_item_placement(name_or_id: str, to_bin: str = "", to_location: str = "",
                       quantity: float = 1) -> str:
    """Stock some of an item in ANOTHER bin/location (multi-location quantities) —
    e.g. 'add 12 AA batteries to the garage bin' when 8 are already in a drawer.
    Adds to the running total; use move_item to relocate the whole thing."""
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify(name_or_id, candidates)
    if not item:
        return f"No item matching '{name_or_id}'."
    payload: dict = {"quantity": quantity}
    if to_bin:
        b, cands = _resolve(to_bin, "bin")
        if cands:
            return _clarify(to_bin, cands, "bin")
        if not b:
            return f"No bin matching '{to_bin}'."
        payload["binId"] = b["id"]
    elif to_location:
        loc, cands = _resolve(to_location, "location")
        if cands:
            return _clarify(to_location, cands, "location")
        if not loc:
            return f"No location matching '{to_location}'."
        payload["locationId"] = loc["id"]
    else:
        return "Tell me which bin or location to stock it in."
    res = _post(f"/items/{item['id']}/holdings", payload)
    return (f"Stocked {quantity} {item['name']} in {to_bin or to_location} "
            f"(total now {res.get('quantity')}).")


@mcp.tool()
def list_checkouts() -> list[dict]:
    """List every item currently checked out (who has it, and if overdue)."""
    data = _get("/checkouts")
    return [
        {"name": i["name"], "to": i.get("checkedOutTo"), "overdue": i.get("overdue")}
        for i in data.get("items", [])
    ]


@mcp.tool()
def check_out_item(name: str, person: str = "", due: str = "") -> str:
    """Check an item out (mark it as not here). Optionally note who has it."""
    item, candidates = _resolve(name)
    if candidates:
        return _clarify(name, candidates)
    if not item:
        return f"No item matching '{name}'."
    if item.get("checkedOut"):
        return f"{item['name']} is already checked out to {item.get('checkedOutTo') or 'someone'}."
    _post(f"/items/{item['id']}/checkout", {"person": person, "due": due or None})
    who = f" to {person}" if person else ""
    return f"Checked out {item['name']}{who}."


@mcp.tool()
def check_in_item(name: str) -> str:
    """Check an item back in (mark it as here)."""
    item, candidates = _resolve(name)
    if candidates:
        return _clarify(name, candidates)
    if not item:
        return f"No item matching '{name}'."
    if not item.get("checkedOut"):
        return f"{item['name']} is already here."
    _post(f"/items/{item['id']}/checkin", {})
    return f"Checked in {item['name']}."


@mcp.tool()
def update_item(
    name_or_id: str,
    name: str = "",
    description: str = "",
    quantity: int = 0,
    notes: str = "",
    manufacturer: str = "",
) -> str:
    """Edit an existing item's details. Only the arguments you pass are changed.

    Note: `quantity` here only applies to a single-location item; for an item
    stored in multiple places the quantity is managed per placement (use
    add_item_placement / move_item), so a `quantity` sent here is ignored.
    Cannot create or delete items — those stay in the HomeHoard app.
    """
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify(name_or_id, candidates)
    if not item:
        return f"No item matching '{name_or_id}'."
    payload: dict = {}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if quantity:
        payload["quantity"] = quantity
    if notes:
        payload["notes"] = notes
    if manufacturer:
        payload["manufacturer"] = manufacturer
    if not payload:
        return "Nothing to change — pass at least one field to update."
    _patch(f"/items/{item['id']}", payload)
    return f"Updated {item['name']}."


@mcp.tool()
def move_item(name_or_id: str, to_bin: str = "", to_location: str = "") -> str:
    """Move an item into a bin or a location (by name)."""
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify(name_or_id, candidates)
    if not item:
        return f"No item matching '{name_or_id}'."
    if to_bin:
        b, cands = _resolve(to_bin, "bin")
        if cands:
            return _clarify(to_bin, cands, "bin")
        if not b:
            return f"No bin matching '{to_bin}'."
        _patch(f"/items/{item['id']}", {"binId": b["id"]})
        return f"Moved {item['name']} into bin {b['name']}."
    if to_location:
        loc, cands = _resolve(to_location, "location")
        if cands:
            return _clarify(to_location, cands, "location")
        if not loc:
            return f"No location matching '{to_location}'."
        _patch(f"/items/{item['id']}", {"locationId": loc["id"], "binId": None})
        return f"Moved {item['name']} to {loc['name']}."
    return "Tell me which bin or location to move it to."


@mcp.tool()
def set_checkout_details(name_or_id: str, person: str = "", due: str = "") -> str:
    """Set who has a checked-out item and/or when it's due (it must be checked out)."""
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify(name_or_id, candidates)
    if not item:
        return f"No item matching '{name_or_id}'."
    if not item.get("checkedOut"):
        return f"{item['name']} isn't checked out."
    payload: dict = {}
    if person:
        payload["person"] = person
    if due:
        payload["due"] = due
    if not payload:
        return "Pass a person and/or a due date."
    _patch(f"/items/{item['id']}/checkout", payload)
    who = f" to {person}" if person else ""
    return f"Updated checkout details for {item['name']}{who}."


@mcp.tool()
def suggest_placement(item: str, labels: str = "") -> list[dict]:
    """Suggest where to put an item, based on where similar items already live.

    Use for "where should I put my ...?" / "where does this go?". `item` is the
    item's name (or a short description). Returns ranked bins/locations, each
    with why it was suggested and a few example items already there. This only
    suggests — use `move_item` to actually place an existing item.
    """
    params = {"name": item}
    if labels:
        params["labels"] = labels
    data = _get("/items/suggest-placement", params)
    out = []
    for s in data.get("suggestions", []):
        where = f" ({s['where']})" if s.get("where") else ""
        why = (
            f"{s['count']} similar item(s) already here"
            if s.get("basis") == "similar"
            else "one of your most-used places"
        )
        out.append(
            {
                "place": f"{s['type']}: {s['name']}{where}",
                "why": why,
                "examples": s.get("samples", []),
            }
        )
    if not out:
        return [{"place": "", "why": "No suggestion — your inventory is empty.",
                 "examples": []}]
    return out


@mcp.tool()
def inventory_statistics() -> dict:
    """Totals + attention counts (items, value, warranties expiring, checked out)."""
    s = _get("/ha/summary")
    return {
        **s.get("totals", {}),
        "warrantiesExpiring30d": s.get("warrantiesExpiring", {}).get("days30"),
        "maintenanceOverdue": s.get("maintenance", {}).get("overdue"),
    }


@mcp.tool()
def inventory_value() -> dict:
    """What everything is worth — total value, insured vs. uninsured, and value
    broken down by location and by label (for an insurance / valuation question)."""
    r = _get("/reports/inventory")
    s = r.get("summary", {})
    return {"currency": r.get("currency"), "totalValue": s.get("totalValue"),
            "insuredValue": s.get("insuredValue"), "uninsuredValue": s.get("uninsuredValue"),
            "itemCount": s.get("totalItems"), "byLocation": r.get("byLocation", []),
            "byLabel": r.get("byLabel", []), "warranty": s.get("warranty", {})}


@mcp.tool()
def warranties_expiring() -> list:
    """Items whose warranty is expiring soon, with the expiry date."""
    return _get("/ha/summary").get("warrantiesExpiring", {}).get("items", [])


@mcp.tool()
def maintenance_due() -> list:
    """Scheduled maintenance that's due or overdue, per item."""
    return _get("/ha/summary").get("maintenance", {}).get("entries", [])


@mcp.tool()
def describe_item(name_or_id: str) -> str:
    """Look an item up online (web search) and store a short searchable description,
    so future searches find it by what it actually is (e.g. a model number → the
    product). Requires a configured Ollama search key."""
    item, candidates = _resolve(name_or_id)
    if candidates:
        return _clarify(name_or_id, candidates)
    if not item:
        return f"No item matching '{name_or_id}'."
    try:
        r = _post(f"/items/{item['id']}/describe")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            return "Web search isn't configured (set an Ollama search key)."
        if e.response.status_code == 422:
            return f"Couldn't find a description for '{item['name']}' online."
        raise
    return r.get("description") or f"Described {item['name']}."


def _require_token(asgi_app, token: str):
    """ASGI wrapper that rejects HTTP requests lacking `Authorization: Bearer
    <token>`. Guards the (otherwise unauthenticated) MCP SSE endpoint so that
    reaching the port isn't enough to read/mutate the inventory."""
    expected = f"Bearer {token}"

    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            presented = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(presented, expected):
                await send({
                    "type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await asgi_app(scope, receive, send)

    return wrapper


# --- External exposure: per-client API-key auth (mirrors Edibl edibl_mcp.py) -------
# When mcp_expose_external is on, the endpoint is reachable from outside HA, so it
# must authenticate every request against a DB-backed, revocable API key with an
# `mcp` (or `full`) scope — not a shared static token. The sidecar builds the Flask
# app once for these read-only key lookups. The entrypoint launches this process with
# HBOX_WORKER_ENABLED=false so create_app() here does NOT start a second AI-job
# worker; migrations are a no-op (the main app already ran them under an flock).
_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def _key_ok(raw: str) -> bool:
    """True if `raw` is a live ApiToken whose scope allows MCP (`mcp` or `full`)."""
    if not raw:
        return False
    try:
        app = _get_app()
        from app.extensions import db
        from app.models import ApiToken, hash_token
        with app.app_context():
            rec = db.session.query(ApiToken).filter_by(token_hash=hash_token(raw)).first()
            ok = rec is not None and (rec.scope or "full") in ("mcp", "full")
            db.session.remove()
            return ok
    except Exception as exc:  # noqa: BLE001 — fail closed on any lookup error
        print(f"homehoard-mcp: key check failed: {exc}", file=sys.stderr)
        return False


# Tools a read-only key may call. Everything else (mutating tools AND any unknown/new
# tool name) is denied to a read key — fail-safe: a new tool is never silently writable.
READ_TOOLS = frozenset({
    "where_is", "search_inventory", "get_item", "get_bin_contents",
    "get_location_contents", "list_checkouts", "suggest_placement",
    "inventory_statistics", "inventory_value", "warranties_expiring", "maintenance_due",
})


def _key_access(raw: str):
    """Access class ('write'|'read') of a live mcp/full ApiToken, or None if the key
    is invalid / not MCP-capable. Fail-closed (None) on any DB error."""
    if not raw:
        return None
    try:
        app = _get_app()
        from app.extensions import db
        from app.models import ApiToken, hash_token
        with app.app_context():
            rec = db.session.query(ApiToken).filter_by(token_hash=hash_token(raw)).first()
            ok = rec is not None and (rec.scope or "full") in ("mcp", "full")
            access = (rec.access or "write") if rec is not None else None
            db.session.remove()
            return access if ok else None
    except Exception as exc:  # noqa: BLE001 — fail closed
        print(f"homehoard-mcp: access check failed: {exc}", file=sys.stderr)
        return None


def _request_access(header_value: str, server_token: str):
    """The access class for an authenticated request ('write'|'read'), or None if
    unauthenticated. The static server token grants full ('write')."""
    if server_token and hmac.compare_digest(header_value, f"Bearer {server_token}"):
        return "write"
    if header_value.startswith("Bearer "):
        return _key_access(header_value[len("Bearer "):].strip())
    return None


async def _buffer_body(receive):
    """Read all http.request messages so the body can be inspected, returning
    (body_bytes, messages) — messages are replayed downstream via _replay()."""
    messages, chunks, more = [], [], True
    while more:
        msg = await receive()
        messages.append(msg)
        if msg["type"] == "http.request":
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        else:
            more = False
    return b"".join(chunks), messages


def _replay(messages):
    it = iter(messages)

    async def receive():
        try:
            return next(it)
        except StopIteration:
            return {"type": "http.disconnect"}

    return receive


async def _read_only_gate(scope, receive, send):
    """For a read-only key: pass the request through unless it is a `tools/call` POST
    for a tool NOT in READ_TOOLS. Returns a receive callable to use downstream, or
    None if it already sent a 403 (caller must stop)."""
    if scope.get("method") != "POST" or "/messages" not in scope.get("path", ""):
        return receive  # GET /sse, initialize, tools/list, ping, etc. — always allowed
    body, messages = await _buffer_body(receive)
    try:
        parsed = json.loads(body or b"{}")
    except Exception:  # noqa: BLE001 — let the MCP layer return its own parse error
        return _replay(messages)
    calls = parsed if isinstance(parsed, list) else [parsed]  # JSON-RPC may batch

    def _is_write(m):
        return (isinstance(m, dict) and m.get("method") == "tools/call"
                and (m.get("params") or {}).get("name") not in READ_TOOLS)

    if any(_is_write(m) for m in calls):
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body",
                    "body": b"read-only API key: this tool mutates data"})
        return None
    return _replay(messages)


def _mcp_key_exists() -> bool:
    """True if a usable key exists to let external clients in — scope `mcp` OR `full`
    (matching what `_key_ok` accepts and the docs' "mint an MCP or Full key"). Used by
    refuse-to-serve. Raises on a DB error so the caller fails closed."""
    app = _get_app()
    from app.extensions import db
    from app.models import ApiToken
    with app.app_context():
        exists = (db.session.query(ApiToken.id)
                  .filter(ApiToken.scope.in_(("mcp", "full"))).first() is not None)
        db.session.remove()
        return exists


def _authorized(header_value: str, server_token: str) -> bool:
    if server_token and hmac.compare_digest(header_value, f"Bearer {server_token}"):
        return True
    if header_value.startswith("Bearer "):
        return _key_ok(header_value[len("Bearer "):].strip())
    return False


def _guard_external(asgi_app, server_token: str):
    """ASGI gate for external exposure: EVERY http request must present a valid
    mcp/full API key (or the optional static server token). Fail-closed."""
    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            access = _request_access(header, server_token)
            if access is None:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
            if access == "read":
                receive = await _read_only_gate(scope, receive, send)
                if receive is None:
                    return  # a mutating tool call was rejected (403 already sent)
        await asgi_app(scope, receive, send)

    return wrapper


def _expose_external() -> bool:
    return bool(_SETTINGS.MCP_EXPOSE_EXTERNAL)


if __name__ == "__main__":
    # Configure logging explicitly here: this process builds its Flask app
    # LAZILY (only when a key lookup needs the DB), so waiting for create_app
    # meant the sidecar produced no log file at all — its own startup and, from
    # here on, its tool-call audit trail went only to stderr.
    from app.logging_setup import configure as _configure_logging
    _configure_logging(_SETTINGS, process="mcp")

    host = _SETTINGS.MCP_HOST
    port = _SETTINGS.MCP_PORT
    server_token = _SETTINGS.MCP_SERVER_TOKEN

    if _expose_external():
        # Fail-closed: never serve an externally-reachable endpoint that nobody can
        # authenticate to. Require a deliberately-minted `mcp` key to exist first.
        try:
            has_key = _mcp_key_exists()
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: homehoard-mcp: could not verify an MCP key exists: {exc}. "
                  "Refusing to serve.", file=sys.stderr)
            sys.exit(1)
        if not has_key:
            print("ERROR: mcp_expose_external is on but no MCP-scoped API key exists. "
                  "Mint one in the app (Tools → API tokens, scope 'MCP'), then restart. "
                  "Refusing to serve an unauthenticated external MCP endpoint.",
                  file=sys.stderr)
            sys.exit(1)
        app = _guard_external(mcp.sse_app(), server_token)
        print("homehoard-mcp: external exposure ON — every request must carry a valid "
              "MCP/Full API key.", file=sys.stderr)
    else:
        app = mcp.sse_app()
        if server_token:
            app = _require_token(app, server_token)
        else:
            print(
                "WARNING: HBOX_MCP_SERVER_TOKEN is not set — the MCP endpoint is "
                "UNAUTHENTICATED. Keep port 7766 on a trusted network, or enable "
                "mcp_expose_external + mint an MCP key to reach it from outside HA.",
                file=sys.stderr,
            )

    import uvicorn
    uvicorn.run(app, host=host, port=port)
