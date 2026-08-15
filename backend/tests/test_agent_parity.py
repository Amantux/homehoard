"""Chat-agent parity: restock, checkouts and duplicate-merge tools.

These surfaces existed on REST (and checkouts on MCP) but were invisible to the
chat assistant. The chat tools are thin wrappers over the same policy code:
restock via services/restock, checkout state like api/checkout, merge like
POST /items/<id>/merge. Merge is destructive, so its resolution refuses
ambiguity (shared services/resolve confidence policy) and is vault-aware —
a hidden item is indistinguishable from an absent one.
"""
from app.extensions import db
from app.models import Item
from app.services.ai.agent import _WRITE_TOOLS, TOOLS, execute_tool


def _tool(gid, name, **args):
    return execute_tool(gid, name, args)


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def _hide(app, item_id):
    with app.app_context():
        db.session.get(Item, item_id).hidden = True
        db.session.commit()


def test_new_tools_are_declared_and_writes_marked():
    names = {t["name"] for t in TOOLS}
    assert {"list_restock", "list_checkouts", "check_out_item",
            "check_in_item", "merge_duplicate_items"} <= names
    assert {"check_out_item", "check_in_item",
            "merge_duplicate_items"} <= _WRITE_TOOLS
    assert {"list_restock", "list_checkouts"}.isdisjoint(_WRITE_TOOLS)


# ---- restock ---------------------------------------------------------------

def test_list_restock_returns_low_items_only(auth_client, app, gid):
    _item(auth_client, "AA batteries", quantity=2, minQuantity=4, targetQuantity=12)
    _item(auth_client, "Couch", quantity=1)  # no policy — never suggested

    with app.app_context():
        rows = _tool(gid, "list_restock")

    assert [r["name"] for r in rows] == ["AA batteries"]
    assert rows[0]["suggestedQuantity"] == 10


def test_list_restock_excludes_hidden_items(auth_client, app, gid):
    low = _item(auth_client, "Secret pills", quantity=0, minQuantity=2)
    _hide(app, low["id"])

    with app.app_context():
        assert _tool(gid, "list_restock") == []


# ---- checkouts -------------------------------------------------------------

def test_check_out_then_list_then_check_in(auth_client, app, gid):
    _item(auth_client, "Ladder")

    with app.app_context():
        out = _tool(gid, "check_out_item", name_or_id="Ladder", person="Sam")
        assert out == {"ok": True, "checkedOut": "Ladder", "to": "Sam"}
        listed = _tool(gid, "list_checkouts")
        db.session.commit()
    assert [(r["name"], r["to"], r["overdue"]) for r in listed] == \
        [("Ladder", "Sam", False)]

    with app.app_context():
        assert _tool(gid, "check_in_item", name_or_id="Ladder")["ok"] is True
        assert _tool(gid, "list_checkouts") == []
        db.session.commit()

    # The chat path wrote the same history REST reads back.
    item_id = auth_client.get("/api/v1/items").get_json()["items"][0]["id"]
    hist = auth_client.get(f"/api/v1/items/{item_id}/checkout").get_json()
    assert hist["checkedOut"] is False
    assert [e["action"] for e in hist["history"]] == ["in", "out"]


def test_check_out_twice_reports_who_has_it(auth_client, app, gid):
    _item(auth_client, "Ladder")
    with app.app_context():
        _tool(gid, "check_out_item", name_or_id="Ladder", person="Sam")
        again = _tool(gid, "check_out_item", name_or_id="Ladder", person="Alex")
    assert again["error"] == "already checked out"
    assert again["checkedOutTo"] == "Sam"


def test_check_in_when_not_out_is_an_error(auth_client, app, gid):
    _item(auth_client, "Ladder")
    with app.app_context():
        assert _tool(gid, "check_in_item", name_or_id="Ladder")["error"] == \
            "not checked out"


def test_list_checkouts_hides_vaulted_items(auth_client, app, gid):
    secret = _item(auth_client, "Secret camera")
    with app.app_context():
        _tool(gid, "check_out_item", name_or_id="Secret camera", person="Sam")
        db.session.commit()
    _hide(app, secret["id"])

    with app.app_context():
        assert _tool(gid, "list_checkouts") == []


# ---- merge -----------------------------------------------------------------

def test_merge_by_id_sums_quantities_and_deletes_source(auth_client, app, gid):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA batteries", quantity=4, locationId=loc["id"])

    with app.app_context():
        out = _tool(gid, "merge_duplicate_items",
                    keep_name_or_id=keep["id"], source_name_or_id=dupe["id"])
        db.session.commit()

    assert out["ok"] is True and out["kept"] == "AA batteries"
    got = auth_client.get(f"/api/v1/items/{keep['id']}").get_json()
    assert got["quantity"] == 10, "quantities did not sum"
    assert got["placementCount"] == 2, "the source's placement was lost"
    assert auth_client.get(f"/api/v1/items/{dupe['id']}").status_code == 404


def test_merge_refuses_ambiguous_name_and_changes_nothing(auth_client, app, gid):
    keep = _item(auth_client, "Toolbox", quantity=1)
    _item(auth_client, "Drill press", quantity=1)
    _item(auth_client, "Drill bits", quantity=1)

    with app.app_context():
        out = _tool(gid, "merge_duplicate_items",
                    keep_name_or_id=keep["id"], source_name_or_id="Drill")
        db.session.commit()

    assert out["needsClarification"] is True
    assert {c["name"] for c in out["candidates"]} == {"Drill press", "Drill bits"}
    names = {i["name"] for i in auth_client.get("/api/v1/items").get_json()["items"]}
    assert names == {"Toolbox", "Drill press", "Drill bits"}, "something was changed"


def test_merge_refuses_self_merge(auth_client, app, gid):
    keep = _item(auth_client, "Toolbox")
    with app.app_context():
        out = _tool(gid, "merge_duplicate_items",
                    keep_name_or_id=keep["id"], source_name_or_id=keep["id"])
    assert out["error"] == "cannot merge an item into itself"


def test_hidden_item_is_not_mergeable(auth_client, app, gid):
    """The vault case: a hidden duplicate looks absent, by id AND by name."""
    keep = _item(auth_client, "Travel wallet", quantity=1)
    secret = _item(auth_client, "Passport", quantity=1)
    _hide(app, secret["id"])

    with app.app_context():
        by_id = _tool(gid, "merge_duplicate_items",
                      keep_name_or_id=keep["id"], source_name_or_id=secret["id"])
        by_name = _tool(gid, "merge_duplicate_items",
                        keep_name_or_id=keep["id"], source_name_or_id="Passport")
        db.session.commit()

    assert by_id["error"] == "no matching duplicate item"
    assert by_name["error"] == "no matching duplicate item"
    with app.app_context():
        assert db.session.get(Item, secret["id"]) is not None, "the vaulted item was destroyed"
