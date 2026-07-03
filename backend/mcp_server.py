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

mcp = FastMCP("HomeHoard")


def _get(path: str, params: dict | None = None):
    r = _HTTP.get(path, params=params)
    r.raise_for_status()
    return r.json()


def _post(path: str, json: dict | None = None):
    r = _HTTP.post(path, json=json or {})
    r.raise_for_status()
    return r.json()


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
def create_item(name: str, location: str = "") -> str:
    """Add a new item to the inventory, optionally in a named location."""
    location_id = None
    if location:
        res = _get("/search", {"q": location, "types": "location"}).get("results", [])
        locs = [r for r in res if r["type"] == "location"]
        if locs:
            location_id = locs[0]["id"]
    item = _post("/items", {"name": name, "locationId": location_id})
    return f"Added '{item['name']}' to the inventory."


@mcp.tool()
def inventory_statistics() -> dict:
    """Totals + attention counts (items, value, warranties expiring, checked out)."""
    s = _get("/ha/summary")
    return {
        **s.get("totals", {}),
        "warrantiesExpiring30d": s.get("warrantiesExpiring", {}).get("days30"),
        "maintenanceOverdue": s.get("maintenance", {}).get("overdue"),
    }


if __name__ == "__main__":
    mcp.settings.host = os.environ.get("HBOX_MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.environ.get("HBOX_MCP_PORT", "7766"))
    mcp.run(transport="sse")
