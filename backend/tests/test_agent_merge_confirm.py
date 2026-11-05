"""merge_duplicate_items deletes a row, so it previews first (prompt-injection guard).

Without confirm=true the tool returns a preview and changes nothing; only an
explicit boolean True merges. Ambiguity refuses even when confirmed.
"""
import pytest

from app.extensions import db
from app.models import Item
from app.services.ai.agent import execute_tool


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def _exists(app, item_id):
    with app.app_context():
        return db.session.get(Item, item_id) is not None


@pytest.mark.parametrize("extra", [{}, {"confirm": False}, {"confirm": "true"}])
def test_merge_without_confirm_previews_and_changes_nothing(auth_client, app, gid, extra):
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA cells", quantity=4)
    with app.app_context():
        out = execute_tool(gid, "merge_duplicate_items",
                           {"keep_name_or_id": keep["id"],
                            "source_name_or_id": dupe["id"], **extra})
        db.session.commit()
    assert out["needsConfirmation"] is True and "ok" not in out
    assert out["keep"]["name"] == "AA batteries" and out["willDelete"] == "AA cells"
    assert set(out["willCombine"]) == {"quantities", "placements", "labels", "attachments"}
    assert _exists(app, dupe["id"]), "the source was deleted without confirmation"
    assert auth_client.get(f"/api/v1/items/{keep['id']}").get_json()["quantity"] == 6


def test_merge_with_confirm_merges(auth_client, app, gid):
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA cells", quantity=4)
    with app.app_context():
        out = execute_tool(gid, "merge_duplicate_items",
                           {"keep_name_or_id": keep["id"],
                            "source_name_or_id": dupe["id"], "confirm": True})
        db.session.commit()
    assert out["ok"] is True and out["merged"] == "AA cells"
    assert not _exists(app, dupe["id"])
    assert auth_client.get(f"/api/v1/items/{keep['id']}").get_json()["quantity"] == 10


def test_ambiguous_with_confirm_still_refuses(auth_client, app, gid):
    keep = _item(auth_client, "Toolbox")
    _item(auth_client, "Drill press")
    _item(auth_client, "Drill bits")
    with app.app_context():
        out = execute_tool(gid, "merge_duplicate_items",
                           {"keep_name_or_id": keep["id"],
                            "source_name_or_id": "Drill", "confirm": True})
        db.session.commit()
    assert out["needsClarification"] is True
    names = {i["name"] for i in auth_client.get("/api/v1/items").get_json()["items"]}
    assert names == {"Toolbox", "Drill press", "Drill bits"}
