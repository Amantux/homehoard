"""P6: barcode lookup must not become an SSRF primitive, and the scanned code must
not be able to reshape the outbound URL. No network: httpx.get is monkeypatched."""
import httpx
import pytest

from app.services import barcode


class _R:
    def raise_for_status(self): pass
    def json(self):
        return {"items": [{"title": "Thing", "brand": "B"}]}


def _record_get(monkeypatch):
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        return _R()
    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_metadata_db_url_is_never_fetched(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True
        app.config["BARCODE_DB_URL"] = "http://169.254.169.254/"
        calls = _record_get(monkeypatch)
        assert barcode._from_product_db("012345678905") is None
        assert "http://169.254.169.254/" not in calls
        assert calls == []


def test_blocked_db_url_falls_through_to_next_source(app, monkeypatch):
    with app.app_context():
        app.config["BARCODE_LOOKUP"] = True
        app.config["BARCODE_DB_URL"] = "http://127.0.0.1:8080/lookup"
        calls = _record_get(monkeypatch)
        monkeypatch.setattr(barcode, "_from_off", lambda c: {
            "name": "Off", "brand": "", "barcode": c, "source": "openfoodfacts"})
        assert barcode.identify_barcode("1")["source"] == "openfoodfacts"
        assert calls == []


def test_public_db_url_is_still_fetched(app, monkeypatch):
    # Positive control: the guard only blocks internal targets. An IP literal
    # avoids DNS, so this exercises the real url_is_safe offline.
    with app.app_context():
        app.config["BARCODE_DB_URL"] = "https://93.184.216.34/lookup"
        calls = _record_get(monkeypatch)
        assert barcode._from_product_db("1")["name"] == "Thing"
        assert calls == ["https://93.184.216.34/lookup"]


def test_off_path_quotes_the_code(app, monkeypatch):
    with app.app_context():
        calls = _record_get(monkeypatch)
        barcode._from_off("../x?y")
        assert calls and calls[0].endswith("/product/..%2Fx%3Fy.json")


@pytest.mark.parametrize("raw", ["1%3Fx", "a%20b", "..", "1" * 65])
def test_identify_rejects_malformed_code(app, auth_client, monkeypatch, raw):
    app.config["BARCODE_LOOKUP"] = True
    seen = []
    monkeypatch.setattr(barcode, "identify_barcode", lambda c: seen.append(c))
    r = auth_client.get(f"/api/v1/items/identify/{raw}")
    assert r.status_code == 400
    assert r.get_json() == {"error": "invalid barcode"}
    assert seen == []
