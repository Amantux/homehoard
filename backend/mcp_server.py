"""HomeHoard MCP server — exposes inventory tools to Home Assistant.

Runs in the same container as the app (a lightweight second process) and simply
calls the local HomeHoard REST API. Home Assistant's **MCP Client** integration
connects to the SSE endpoint and can then answer things like "where is my drill?"
or check items in/out via Assist.

Run:  python mcp_server.py    (serves SSE on HBOX_MCP_HOST:HBOX_MCP_PORT/sse)
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("HBOX_MCP_API", "http://127.0.0.1:7745/api/v1")
TOKEN = os.environ.get("HBOX_MCP_API_TOKEN")  # only needed if app auth is enabled
_HEADERS = {"Authorization": TOKEN} if TOKEN else {}
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


def _resolve_named(kind: str, name: str):
    """First bin/location result matching ``name`` (or None)."""
    res = _get("/search", {"q": name, "types": kind}).get("results", [])
    hits = [r for r in res if r["type"] == kind]
    return hits[0] if hits else None


def _resolve_item(name_or_id: str):
    """Find a single item by id or name (first search match)."""
    try:
        return _get(f"/items/{name_or_id}")
    except httpx.HTTPStatusError:
        pass
    res = _get("/search", {"q": name_or_id, "types": "item"}).get("results", [])
    if not res:
        return None
    return _get(f"/items/{res[0]['id']}")


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
    item = _resolve_item(name_or_id)
    if not item:
        return {"error": f"No item matching '{name_or_id}'."}
    return {
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description"),
        "quantity": item.get("quantity"),
        "location": (item.get("location") or {}).get("name"),
        "bin": (item.get("bin") or {}).get("name"),
        "checkedOut": item.get("checkedOut"),
        "checkedOutTo": item.get("checkedOutTo"),
        "manufacturer": item.get("manufacturer"),
        "purchasePrice": item.get("purchasePrice"),
    }


@mcp.tool()
def get_bin_contents(name: str) -> dict:
    """List what's inside a bin (by name)."""
    res = _get("/search", {"q": name, "types": "bin"}).get("results", [])
    bins = [r for r in res if r["type"] == "bin"]
    if not bins:
        return {"error": f"No bin matching '{name}'."}
    b = _get(f"/bins/{bins[0]['id']}")
    return {"bin": b["name"], "items": [i["name"] for i in b.get("items", [])]}


@mcp.tool()
def get_location_contents(name: str) -> dict:
    """List items and bins in a location (by name)."""
    res = _get("/search", {"q": name, "types": "location"}).get("results", [])
    locs = [r for r in res if r["type"] == "location"]
    if not locs:
        return {"error": f"No location matching '{name}'."}
    loc = _get(f"/locations/{locs[0]['id']}")
    return {
        "location": loc["name"],
        "items": [i["name"] for i in loc.get("items", [])],
        "bins": [b["name"] for b in loc.get("bins", [])],
    }


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
    item = _resolve_item(name)
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
    item = _resolve_item(name)
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

    Cannot create or delete items — those stay in the HomeHoard app.
    """
    item = _resolve_item(name_or_id)
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
    item = _resolve_item(name_or_id)
    if not item:
        return f"No item matching '{name_or_id}'."
    if to_bin:
        b = _resolve_named("bin", to_bin)
        if not b:
            return f"No bin matching '{to_bin}'."
        _patch(f"/items/{item['id']}", {"binId": b["id"]})
        return f"Moved {item['name']} into bin {b['name']}."
    if to_location:
        loc = _resolve_named("location", to_location)
        if not loc:
            return f"No location matching '{to_location}'."
        _patch(f"/items/{item['id']}", {"locationId": loc["id"], "binId": None})
        return f"Moved {item['name']} to {loc['name']}."
    return "Tell me which bin or location to move it to."


@mcp.tool()
def set_checkout_details(name_or_id: str, person: str = "", due: str = "") -> str:
    """Set who has a checked-out item and/or when it's due (it must be checked out)."""
    item = _resolve_item(name_or_id)
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


def _require_token(asgi_app, token: str):
    """ASGI wrapper that rejects HTTP requests lacking `Authorization: Bearer
    <token>`. Guards the (otherwise unauthenticated) MCP SSE endpoint so that
    reaching the port isn't enough to read/mutate the inventory."""
    expected = f"Bearer {token}"

    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"").decode() != expected:
                await send({
                    "type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await asgi_app(scope, receive, send)

    return wrapper


if __name__ == "__main__":
    host = os.environ.get("HBOX_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("HBOX_MCP_PORT", "7766"))
    server_token = os.environ.get("HBOX_MCP_SERVER_TOKEN", "")

    app = mcp.sse_app()
    if server_token:
        app = _require_token(app, server_token)
    else:
        import sys
        print(
            "WARNING: HBOX_MCP_SERVER_TOKEN is not set — the MCP endpoint is "
            "UNAUTHENTICATED. Set it and keep port 7766 on a trusted network.",
            file=sys.stderr,
        )

    import uvicorn
    uvicorn.run(app, host=host, port=port)
