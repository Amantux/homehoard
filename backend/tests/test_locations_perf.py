"""P38: /locations, /locations/tree and /ha/summary cost O(rows returned).

- the tree is built from one query, so its query count does not grow with the
  number of locations;
- a parent cycle written straight to the DB (the API refuses one) still
  renders instead of recursing until RecursionError;
- the grouped COUNT keeps the vault rule: a hidden item is not counted while
  locked, and is once unlocked.
"""
from contextlib import contextmanager

from sqlalchemy import event

from app.extensions import db
from app.models import Item, Location


@contextmanager
def _count_queries(app):
    counter = {"n": 0}

    def _on(*_a, **_k):
        counter["n"] += 1

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _on)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _on)


def _loc(c, name, parent=None):
    body = {"name": name}
    if parent:
        body["parentId"] = parent
    r = c.post("/api/v1/locations", json=body)
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    return r.get_json()["id"]


def _tree_queries(app, c):
    with _count_queries(app) as n:
        r = c.get("/api/v1/locations/tree")
    assert r.status_code == 200
    return n["n"]


def _nested(c, count):
    """`count` locations: chains of three (root > child > grandchild)."""
    for i in range(count // 3):
        a = _loc(c, f"Root {i}")
        b = _loc(c, f"Child {i}", a)
        _loc(c, f"Grandchild {i}", b)


def test_tree_query_count_is_constant(app, auth_client):
    _nested(auth_client, 3)
    small = _tree_queries(app, auth_client)
    _nested(auth_client, 27)  # 30 in total
    large = _tree_queries(app, auth_client)
    assert large == small, f"tree went from {small} to {large} queries"


def test_tree_shape_is_unchanged(auth_client):
    a = _loc(auth_client, "House")
    b = _loc(auth_client, "Kitchen", a)
    _loc(auth_client, "Drawer", b)
    _loc(auth_client, "Garage")
    tree = auth_client.get("/api/v1/locations/tree").get_json()
    by_name = {n["name"]: n for n in tree}
    assert set(by_name) == {"House", "Garage"}
    house = by_name["House"]
    assert house["type"] == "location" and house["id"] == a
    assert [c["name"] for c in house["children"]] == ["Kitchen"]
    assert [c["name"] for c in house["children"][0]["children"]] == ["Drawer"]
    assert house["children"][0]["children"][0]["children"] == []


def test_forced_cycle_returns_200(app, auth_client):
    """A > B > A written straight to the DB (the API refuses it). With one
    parent_id per row no loop can hang off a NULL root, so the endpoint must
    simply answer — the serializer-level test below is the mutation target."""
    top = _loc(auth_client, "Top")
    a = _loc(auth_client, "A")
    b = _loc(auth_client, "B", a)
    with app.app_context():
        db.session.get(Location, a).parent_id = b
        db.session.commit()
    r = auth_client.get("/api/v1/locations/tree")
    assert r.status_code == 200
    assert [n["id"] for n in r.get_json()] == [top]
    assert auth_client.get(f"/api/v1/locations/{b}").status_code == 200
    assert auth_client.get("/api/v1/locations").status_code == 200


def test_location_tree_seen_guard_cuts_a_revisited_node(app):
    """Direct check on the serializer: a children map that loops back must
    emit the revisited node without its children rather than recurse."""
    from app.schemas.serializers import location_tree

    with app.app_context():
        a = Location(name="A")
        b = Location(name="B")
        a.id, b.id = "a", "b"
        children = {"a": [b], "b": [a]}
        out = location_tree(a, children)
    assert out["children"][0]["name"] == "B"
    assert out["children"][0]["children"][0] == {
        "id": "a", "name": "A", "type": "location", "children": []}


def test_list_counts_follow_the_vault(app, auth_client):
    loc = _loc(auth_client, "Shed")
    bin_r = auth_client.post("/api/v1/bins", json={"name": "Crate", "locationId": loc})
    assert bin_r.status_code in (200, 201), bin_r.get_data(as_text=True)
    bin_id = bin_r.get_json()["id"]
    auth_client.post("/api/v1/items", json={"name": "Rake", "locationId": loc})
    auth_client.post("/api/v1/items", json={"name": "Hose", "binId": bin_id})
    secret = auth_client.post(
        "/api/v1/items", json={"name": "Secret", "binId": bin_id}).get_json()
    with app.app_context():
        db.session.get(Item, secret["id"]).hidden = True
        db.session.commit()

    def counts():
        row = next(x for x in auth_client.get("/api/v1/locations").get_json()
                   if x["id"] == loc)
        return row["itemCount"], row["bins"][0]["itemCount"]

    assert counts() == (2, 1), "a hidden item was counted while locked"
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})
    r = auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    assert r.status_code == 200
    assert counts() == (3, 2), "an unlocked vault lost the hidden item"


def test_ha_summary_and_calendar_accept_any_offset(app, auth_client):
    """/ha/summary totals come from SQL; ``_parse`` normalises ANY offset to
    naive UTC (it used to strip only a literal "+00:00", so "+02:00" left an
    aware datetime that 500'd against the naive stored dates)."""
    from datetime import datetime, timedelta

    item = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()
    with app.app_context():
        db.session.get(Item, item["id"]).warranty_expires = (
            datetime.utcnow() + timedelta(days=10))
        db.session.commit()
    totals = auth_client.get("/api/v1/ha/summary").get_json()["totals"]
    assert totals["items"] == 1 and totals["withWarranty"] == 1
    r = auth_client.get("/api/v1/ha/calendar",
                        query_string={"start": "2000-01-01T02:00:00+02:00",
                                      "end": "2100-01-01T00:00:00-05:00"})
    assert r.status_code == 200
    assert any(e["itemId"] == item["id"] for e in r.get_json())
