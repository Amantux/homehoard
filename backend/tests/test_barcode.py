"""Barcode identification (product DB → Open Food Facts → web search) + scan resolve.

External HTTP is monkeypatched — no network here; the chain, the /barcode resolve,
and the /items/identify endpoint are covered.
"""
from datetime import datetime

import httpx

from app.extensions import db
from app.models import Item, User
from app.services import barcode


def _gid(app):
    with app.app_context():
        return db.session.query(User).filter_by(email="t@t.com").first().group_id


# --- identify_barcode chain -------------------------------------------------

def test_lookup_disabled_returns_none(app):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = False
        assert barcode.identify_barcode("012345678905") is None


def test_product_db_hit_short_circuits(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True
        monkeypatch.setattr(barcode, "_from_product_db",
                            lambda c: {"name": "Drill", "source": "productdb"})
        seen = []
        monkeypatch.setattr(barcode, "_from_off", lambda c: seen.append("off"))
        assert barcode.identify_barcode("1")["source"] == "productdb" and not seen


def test_falls_through_db_off_websearch(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True
        monkeypatch.setattr(barcode, "_from_product_db", lambda c: None)
        monkeypatch.setattr(barcode, "_from_off", lambda c: None)
        monkeypatch.setattr(barcode, "_from_web_search",
                            lambda c: {"name": "X", "source": "websearch"})
        assert barcode.identify_barcode("1")["source"] == "websearch"


def test_all_miss_returns_none(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True
        for fn in ("_from_product_db", "_from_off", "_from_web_search"):
            monkeypatch.setattr(barcode, fn, lambda c: None)
        assert barcode.identify_barcode("1") is None


def test_product_db_parses(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True

        class _R:
            def raise_for_status(self): pass
            def json(self):
                return {"items": [{"title": "DeWalt DCD777", "brand": "DeWalt"}]}
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
        r = barcode._from_product_db("012345678905")
        assert r["name"] == "DeWalt DCD777" and r["brand"] == "DeWalt"
        assert r["source"] == "productdb"


def test_clean_title_extracts_product_segment():
    # An aggregator/lookup page yields no product segment...
    assert barcode._clean_title("UPC 012345678905 | Barcode Lookup", "012345678905") is None
    # ...a real product title yields the product part, dropping the retailer tail.
    assert (barcode._clean_title("Great Value Whole Milk 1 Gal | Walmart", "0")
            == "Great Value Whole Milk 1 Gal")


def test_web_search_prefers_clean_segment(app, monkeypatch):
    with app.app_context():
        from app.services import enrich
        monkeypatch.setattr(enrich, "enabled", lambda: True)
        monkeypatch.setattr(enrich, "_cfg", lambda: {"key": "k"})
        monkeypatch.setattr(enrich, "web_search", lambda q, key: [
            {"title": "UPC 012345678905 | Barcode Lookup"},   # junk → skipped
            {"title": "Organic Whole Milk 1qt | Amazon"},     # real product
        ])
        monkeypatch.setattr(enrich, "extract_product", lambda results, cfg: None)  # no LLM
        hit = barcode._from_web_search("012345678905")
    assert hit["name"] == "Organic Whole Milk 1qt" and hit["source"] == "websearch"


def test_web_search_uses_llm_extraction(app, monkeypatch):
    with app.app_context():
        from app.services import enrich
        monkeypatch.setattr(enrich, "enabled", lambda: True)
        monkeypatch.setattr(enrich, "_cfg",
                            lambda: {"key": "k", "url": "http://x", "model": "m"})
        monkeypatch.setattr(enrich, "web_search",
                            lambda q, key: [{"title": "UPC | Barcode Lookup",
                                             "content": "", "url": "http://upcitemdb.com/x"}])
        monkeypatch.setattr(enrich, "extract_product",
                            lambda results, cfg: {"name": "Organic Milk", "brand": "GV"})
        hit = barcode._from_web_search("012345678905")
    assert hit == {"name": "Organic Milk", "brand": "GV",
                   "barcode": "012345678905", "source": "websearch"}


def test_rank_results_sinks_aggregators():
    from app.services import enrich
    ranked = enrich.rank_results([{"url": "http://barcodelookup.com/a"},
                                  {"url": "http://walmart.com/b"}])
    assert "walmart" in ranked[0]["url"]  # real retailer ranked ahead of the aggregator


# --- scan resolve + identify endpoints --------------------------------------

def test_barcode_resolve_returns_item_by_barcode(app, auth_client):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Drill", barcode="012345678905", group_id=gid))
        db.session.commit()

    r = auth_client.get("/api/v1/barcode/012345678905").get_json()

    assert r["status"] == "item" and r["target"]["name"] == "Drill"


def test_barcode_resolve_not_found(app, auth_client):
    assert auth_client.get("/api/v1/barcode/nope").get_json()["status"] == "not_found"


def test_identify_disabled_409(app, auth_client):
    app.config["BARCODE_LOOKUP"] = False
    assert auth_client.get("/api/v1/items/identify/999").status_code == 409


def test_identify_returns_suggestion(app, auth_client, monkeypatch):
    app.config["BARCODE_LOOKUP"] = True
    from app.services import barcode as bc
    monkeypatch.setattr(bc, "identify_barcode",
                        lambda code: {"name": "DeWalt DCD777", "brand": "DeWalt",
                                      "barcode": code, "source": "productdb"})
    r = auth_client.get("/api/v1/items/identify/012345678905").get_json()
    assert r["status"] == "suggestion" and r["suggestion"]["name"] == "DeWalt DCD777"


def test_create_item_persists_barcode(app, auth_client):
    created = auth_client.post(
        "/api/v1/items", json={"name": "Drill", "barcode": "012345678905"}
    ).get_json()

    assert created["barcode"] == "012345678905"
    # ...and it now resolves on a scan.
    r = auth_client.get("/api/v1/barcode/012345678905").get_json()
    assert r["status"] == "item" and r["targetId"] == created["id"]


def test_barcode_resolve_is_group_scoped(app):
    """Group B scanning group A's product barcode gets not_found — no cross-group leak."""
    app.config["ALLOW_REGISTRATION"] = True
    a, b = app.test_client(), app.test_client()

    def _reg(c, email):
        c.post("/api/v1/users/register",
               json={"email": email, "password": "password", "name": email})
        tok = c.post("/api/v1/users/login",
                     json={"username": email, "password": "password"}).get_json()["token"]
        c.environ_base["HTTP_AUTHORIZATION"] = tok

    _reg(a, "a@a.com")
    _reg(b, "b@b.com")
    a.post("/api/v1/items", json={"name": "Drill", "barcode": "012345678905"})

    assert b.get("/api/v1/barcode/012345678905").get_json()["status"] == "not_found"


def test_create_clamps_overlong_barcode(app, auth_client):
    """A pasted 2D/QR value can't overflow Item.barcode (String(64)) → no 500."""
    long_code = "https://example.com/" + "x" * 300

    created = auth_client.post(
        "/api/v1/items", json={"name": "Thing", "barcode": long_code}
    ).get_json()

    assert len(created["barcode"]) == 64


def test_duplicate_barcode_resolves_deterministically_oldest_first(app, auth_client):
    """Two items sharing a UPC resolve to the same (oldest) one on every scan."""
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Drill A", barcode="012345678905", group_id=gid,
                            created_at=datetime(2020, 1, 1)))
        newer = Item(name="Drill B", barcode="012345678905", group_id=gid,
                     created_at=datetime(2021, 1, 1))
        db.session.add(newer)
        db.session.commit()
        newer_id = newer.id

    r = auth_client.get("/api/v1/barcode/012345678905").get_json()

    assert r["status"] == "item" and r["target"]["name"] == "Drill A"
    assert r["targetId"] != newer_id


def test_update_item_assigns_barcode(app, auth_client):
    """Editing an item to add a barcode persists it and makes the item scannable."""
    item_id = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()["id"]

    auth_client.put(f"/api/v1/items/{item_id}", json={"name": "Drill",
                                                      "barcode": "012345678905"})

    r = auth_client.get("/api/v1/barcode/012345678905").get_json()
    assert r["status"] == "item" and r["targetId"] == item_id


def test_item_search_matches_barcode(app, auth_client):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Drill", barcode="012345678905", group_id=gid))
        db.session.commit()

    found = auth_client.get("/api/v1/items?q=012345").get_json()

    assert "Drill" in [i["name"] for i in found["items"]]
