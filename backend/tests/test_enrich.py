"""AI web-searched searchable descriptions (Ollama web search).

The live web-search HTTP call is monkeypatched (no key/network here); with the
synthesis model URL blanked, `describe` falls back to the top result's snippet,
so these tests are deterministic and offline.
"""
from sqlalchemy import inspect

from app.auth import create_token
from app.extensions import db
from app.models import Group, Item, User


def _gid(app):
    with app.app_context():
        return db.session.query(User).filter_by(email="t@t.com").first().group_id


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


def test_describe_stores_text_and_makes_item_findable(app, auth_client, monkeypatch):
    gid = _gid(app)
    _enable(app, monkeypatch, [{"title": "t", "url": "http://x",
                                "content": "DeWalt 20V MAX brushless cordless drill"}])
    iid = _mk_item(app, gid)

    r = auth_client.post(f"/api/v1/items/{iid}/describe")

    assert r.status_code == 200
    assert "brushless" in r.get_json()["searchText"].lower()
    # Now findable by a word only present in the web-searched description.
    found = auth_client.get("/api/v1/items?q=brushless").get_json()
    assert "DCD777" in [i["name"] for i in found["items"]]


def test_describe_409_when_not_configured(app, auth_client):
    gid = _gid(app)
    app.config["OLLAMA_SEARCH_KEY"] = ""
    iid = _mk_item(app, gid)
    assert auth_client.post(f"/api/v1/items/{iid}/describe").status_code == 409


def test_describe_422_when_nothing_found(app, auth_client, monkeypatch):
    gid = _gid(app)
    _enable(app, monkeypatch, [])  # web search returns nothing
    iid = _mk_item(app, gid)
    assert auth_client.post(f"/api/v1/items/{iid}/describe").status_code == 422


def test_describe_missing_only_enriches_blank(app, auth_client, monkeypatch):
    gid = _gid(app)
    _enable(app, monkeypatch, [{"content": "a cordless drill"}])
    _mk_item(app, gid, name="Blank", search_text="")
    _mk_item(app, gid, name="Already", search_text="already described")

    r = auth_client.post("/api/v1/items/describe-missing").get_json()

    assert r["described"] == 1 and r["scanned"] == 1  # only the blank one


def test_describe_missing_forbidden_for_non_owner(app):
    # The bulk (paid) batch is owner-only.
    with app.app_context():
        g = Group(name="H", currency="usd")
        db.session.add(g)
        db.session.flush()
        member = User(name="M", email="m@x.com", password_hash="x",
                      is_superuser=False, is_owner=False, group_id=g.id)
        db.session.add(member)
        db.session.commit()
        token = create_token(member)
    r = app.test_client().post("/api/v1/items/describe-missing",
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
