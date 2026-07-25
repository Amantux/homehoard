"""Identify a scanned product barcode (UPC/EAN) → name/brand, so a scan can
find-or-create the right item.

Chains a general product barcode DB → Open Food Facts (grocery) → an Ollama
web-search fallback. Best-effort, bounded, never raises; off unless
HBOX_BARCODE_LOOKUP is set. Returns ``{name, brand, barcode, source}`` or None.
"""
import logging
import re

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


# Words that mark a search-result title as an aggregator/listing page, not a product.
_TITLE_JUNK = re.compile(
    r"\b(upc|ean|gtin|barcode|bar code|lookup|database|scanner|price|prices|"
    r"buy|shop|amazon|ebay|walmart|target)\b", re.I)


def _clean_title(title, code):
    """Turn a search-result page title into a plausible product name: drop the
    barcode digits, split on separators, and pick the first segment that looks like
    a product (not an aggregator page). None if no such segment exists."""
    t = (title or "").replace(code, " ")
    for part in re.split(r"\s*[|–—:·]\s*|\s+-\s+", t):
        part = part.strip()
        if len(part) >= 3 and not part.isdigit() and not _TITLE_JUNK.search(part):
            return part[:80]
    return None


def _from_web_search(code):
    from . import enrich

    if not enrich.enabled():
        return None
    results = enrich.web_search(f"{code} UPC barcode product", key=enrich._cfg()["key"]) or []
    # Prefer a clean product-looking segment from the first few results; only if none
    # exists fall back to the raw first title (better than nothing).
    name = next((c for c in (_clean_title(r.get("title"), code) for r in results[:4]) if c),
                None)
    if not name and results:
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
