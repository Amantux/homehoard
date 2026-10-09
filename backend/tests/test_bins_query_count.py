"""GET /bins is O(1) queries in the number of bins, and list routes take ?limit."""
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Bin, Item, ItemHolding, Label, Location


@contextmanager
def _count_queries(app):
    counter = {"n": 0, "sql": []}

    def _before(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1
        counter["sql"].append(statement)

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _make_bins(app, gid, n_bins, holdings_per_bin):
    with app.app_context():
        for b_i in range(n_bins):
            b = Bin(name=f"bin{b_i}", group_id=gid)
            db.session.add(b)
            db.session.flush()
            for h_i in range(holdings_per_bin):
                item = Item(name=f"item{b_i}-{h_i}", group_id=gid)
                db.session.add(item)
                db.session.flush()
                db.session.add(ItemHolding(item_id=item.id, bin_id=b.id,
                                           group_id=gid, quantity=1))
        db.session.commit()


def _bins_query_count(app, auth_client):
    with _count_queries(app) as c:
        r = auth_client.get("/api/v1/bins")
    assert r.status_code == 200
    # No holding ROWS hydrated: only the aggregate touches item_holdings.
    assert not any("item_holdings.quantity" in s for s in c["sql"])
    return c["n"], r.get_json()


def test_bin_list_query_count_is_constant(app, auth_client, gid):
    _make_bins(app, gid, 1, 3)
    n_one, body_one = _bins_query_count(app, auth_client)
    assert [b["itemCount"] for b in body_one] == [3]

    _make_bins(app, gid, 2, 3)
    n_three, body_three = _bins_query_count(app, auth_client)
    assert len(body_three) == 3
    assert all(b["itemCount"] == 3 for b in body_three)
    assert n_three == n_one


def test_bin_without_holdings_counts_zero(app, auth_client, gid):
    _make_bins(app, gid, 1, 0)
    _, body = _bins_query_count(app, auth_client)
    assert [b["itemCount"] for b in body] == [0]


@pytest.mark.parametrize("path", ["/api/v1/bins", "/api/v1/locations",
                                  "/api/v1/labels"])
def test_list_limit(app, auth_client, gid, path):
    with app.app_context():
        for i in range(3):
            db.session.add(Bin(name=f"b{i}", group_id=gid))
            db.session.add(Location(name=f"l{i}", group_id=gid))
            db.session.add(Label(name=f"t{i}", group_id=gid))
        db.session.commit()

    r = auth_client.get(f"{path}?limit=2")
    assert r.status_code == 200 and len(r.get_json()) == 2
    assert len(auth_client.get(path).get_json()) == 3
    assert auth_client.get(f"{path}?limit=abc").status_code == 400
    r = auth_client.get(f"{path}?limit=5000")
    assert r.status_code == 200 and len(r.get_json()) <= 1000


def test_checkouts_limit(auth_client):
    assert auth_client.get("/api/v1/checkouts?limit=abc").status_code == 400
    r = auth_client.get("/api/v1/checkouts?limit=5000")
    assert r.status_code == 200 and r.get_json()["items"] == []


def test_locations_filter_children_with_limit(app, auth_client, gid):
    with app.app_context():
        parent = Location(name="p", group_id=gid)
        db.session.add(parent)
        db.session.flush()
        db.session.add(Location(name="c", group_id=gid, parent_id=parent.id))
        db.session.commit()
    body = auth_client.get("/api/v1/locations?filterChildren=true&limit=1").get_json()
    assert [loc["name"] for loc in body] == ["p"]
