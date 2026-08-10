"""AI web-searched searchable descriptions (Ollama web search).

The live web-search HTTP call is monkeypatched (no key/network here); with the
synthesis model URL blanked, `describe` falls back to the top result's snippet,
so these tests are deterministic and offline.
"""
from sqlalchemy import inspect

from app.extensions import db
from app.models import Item


def _mk_item(app, gid, name="DCD777", search_text=""):
    with app.app_context():
        it = Item(name=name, group_id=gid, search_text=search_text)
        db.session.add(it)
        db.session.commit()
        return it.id


def _enable(app, monkeypatch, results):
    from app.services import enrich
    app.config["OLLAMA_SEARCH_KEY"] = "k"
    app.config["OLLAMA_URL"] = ""  # blank → skip the model, use the snippet fallback
    monkeypatch.setattr(enrich, "web_search", lambda q, **kw: results)


def test_migration_added_search_text_column(app):
    with app.app_context():
        cols = {c["name"] for c in inspect(db.engine).get_columns("items")}
    assert "search_text" in cols


def test_describe_stores_text_and_makes_item_findable(app, auth_client, monkeypatch, gid):

    _enable(app, monkeypatch, [{"title": "t", "url": "http://x",
                                "content": "DeWalt 20V MAX brushless cordless drill"}])
    iid = _mk_item(app, gid)

    r = auth_client.post(f"/api/v1/items/{iid}/describe")

    assert r.status_code == 200
    assert "brushless" in r.get_json()["searchText"].lower()
    # Now findable by a word only present in the web-searched description.
    found = auth_client.get("/api/v1/items?q=brushless").get_json()
    assert "DCD777" in [i["name"] for i in found["items"]]


def test_describe_409_when_not_configured(app, auth_client, gid):

    app.config["OLLAMA_SEARCH_KEY"] = ""
    iid = _mk_item(app, gid)
    assert auth_client.post(f"/api/v1/items/{iid}/describe").status_code == 409


def test_describe_422_when_nothing_found(app, auth_client, monkeypatch, gid):

    _enable(app, monkeypatch, [])  # web search returns nothing
    iid = _mk_item(app, gid)
    assert auth_client.post(f"/api/v1/items/{iid}/describe").status_code == 422


# Bulk enrichment moved to an async job (POST /jobs/enrich); see test_jobs.py for
# its owner-only guard and per-item processing.
