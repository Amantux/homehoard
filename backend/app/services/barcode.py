"""Look up product info for a barcode from free public databases.

Tries Open Food Facts (great for groceries/household) then UPCitemdb's trial
endpoint (general products). Best-effort and fully offline-safe: any network or
parse error just yields ``None`` so the caller can fall back to manual entry.
"""
import json
import urllib.request

_TIMEOUT = 6
_UA = "HomeHoard/1.0 (+https://github.com/Amantux/homehoard)"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _from_openfoodfacts(code: str):
    data = _get_json(f"https://world.openfoodfacts.org/api/v0/product/{code}.json")
    if data.get("status") != 1:
        return None
    p = data.get("product", {})
    name = p.get("product_name") or p.get("generic_name")
    if not name:
        return None
    return {
        "name": name.strip(),
        "manufacturer": (p.get("brands") or "").split(",")[0].strip(),
        "imageUrl": p.get("image_front_url") or p.get("image_url") or "",
        "category": (p.get("categories") or "").split(",")[0].strip(),
        "source": "openfoodfacts",
    }


def _from_upcitemdb(code: str):
    data = _get_json(f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}")
    items = data.get("items") or []
    if not items:
        return None
    it = items[0]
    if not it.get("title"):
        return None
    return {
        "name": it["title"].strip(),
        "manufacturer": (it.get("brand") or "").strip(),
        "imageUrl": (it.get("images") or [""])[0],
        "category": (it.get("category") or "").strip(),
        "source": "upcitemdb",
    }


def lookup_product(code: str):
    code = (code or "").strip()
    if not code:
        return None
    for provider in (_from_openfoodfacts, _from_upcitemdb):
        try:
            result = provider(code)
            if result:
                return result
        except Exception:  # noqa: BLE001 - network/parse errors are non-fatal
            continue
    return None
