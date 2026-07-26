"""Opt-in integration smoke: hit the REAL Open Food Facts API (public, no key).

Skipped unless RUN_INTEGRATION=1, so normal/offline CI never depends on the
network. This is the one check that would catch a breaking change in OFF's
response shape — the mocked unit tests in test_barcode.py cannot.

Run with:  RUN_INTEGRATION=1 python3 -m pytest tests/test_integration_barcode.py
"""
import os

import pytest

from app.services import barcode

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="network integration test; set RUN_INTEGRATION=1 to run",
)

# Nutella 400g — a long-stable Open Food Facts entry that carries a product_name.
NUTELLA = "3017620422003"


# Apple iPhone 6 UPC — a stable UPCitemdb entry with a title.
IPHONE_UPC = "0885909950805"


def test_off_lookup_real_returns_named_product():
    hit = barcode._from_off(NUTELLA)

    assert hit is not None, "OFF returned nothing — network down or response shape changed"
    assert hit["name"], "OFF product had no parseable name — response shape may have changed"
    assert hit["source"] == "openfoodfacts"
    assert hit["barcode"] == NUTELLA


def test_product_db_lookup_real_returns_named_product(app):
    """Hit the real UPCitemdb trial endpoint (keyless) via app config."""
    with app.app_context():
        hit = barcode._from_product_db(IPHONE_UPC)

    assert hit is not None, "product DB returned nothing — trial quota, network, or shape change"
    assert hit["name"], "product DB entry had no title — response shape may have changed"
    assert hit["source"] == "productdb"
    assert hit["barcode"] == IPHONE_UPC


def test_web_search_real(app):
    """Exercise the real Ollama web-search path — only when a key is configured."""
    from app.services import enrich
    with app.app_context():
        if not enrich.enabled():
            pytest.skip("no OLLAMA_SEARCH_KEY configured")
        results = enrich.web_search("3017620422003 nutella product",
                                    key=enrich._cfg()["key"])
    assert results, "web_search returned nothing — key/quota/shape issue"
