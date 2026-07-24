"""Identify a scanned product barcode (UPC/EAN) → name/brand, so a scan can
find-or-create the right item.

Chains a general product barcode DB → Open Food Facts (grocery) → an Ollama
web-search fallback. Best-effort, bounded, never raises; off unless
HBOX_BARCODE_LOOKUP is set. Returns ``{name, brand, barcode, source}`` or None.
"""
import logging

from flask import current_app

_LOGGER = logging.getLogger("homehoard.barcode")


def _from_product_db(code):
    import httpx

    base = current_app.config.get("BARCODE_DB_URL")
    if not base:
        return None
    key = current_app.config.get("BARCODE_DB_KEY")
    headers = {"user_key": key, "key_type": "3scale"} if key else {}
    try:
        r = httpx.get(base, params={"upc": code}, headers=headers, timeout=6)
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
    except Exception as exc:  # noqa: BLE001 — best-effort
        _LOGGER.info("product-DB lookup failed for %s: %s", code, exc)
        return None
    if not items:
        return None
    it = items[0]
    name = (it.get("title") or "").strip()
    if not name:
        return None
    return {"name": name, "brand": (it.get("brand") or "").strip(),
            "barcode": code, "source": "productdb"}


def _from_off(code):
    import httpx

    url = f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
    try:
        r = httpx.get(url, timeout=6, headers={"User-Agent": "HomeHoard/1.0"})
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001 — best-effort
        _LOGGER.info("OFF lookup failed for %s: %s", code, exc)
        return None
    if data.get("status") != 1:
        return None
    p = data.get("product") or {}
    name = (p.get("product_name") or p.get("generic_name") or "").strip()
    if not name:
        return None
    return {"name": name, "brand": (p.get("brands") or "").split(",")[0].strip(),
            "barcode": code, "source": "openfoodfacts"}


def _from_web_search(code):
    from . import enrich

    if not enrich.enabled():
        return None
    results = enrich.web_search(f"{code} UPC barcode product", key=enrich._cfg()["key"])
    if not results:
        return None
    name = (results[0].get("title") or "").strip()[:80]
    if not name:
        return None
    return {"name": name, "brand": "", "barcode": code, "source": "websearch"}


def identify_barcode(code: str):
    """Identify a product from its barcode, or None. Guarded by config so offline
    installs never touch the network; each step best-effort, degrading to the next.
    """
    if not code or not current_app.config.get("BARCODE_LOOKUP"):
        return None
    return _from_product_db(code) or _from_off(code) or _from_web_search(code)
