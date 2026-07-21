"""Multi-location quantities: an item can be stocked across multiple bins, each
holding its own quantity, rolling up to the item's total. item.quantity /
location / bin stay a synced cache of the holdings (source of truth)."""


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _bin(c, name, loc_id):
    return c.post("/api/v1/bins", json={"name": name, "locationId": loc_id}).get_json()


def _item(c, **kw):
    return c.post("/api/v1/items", json=kw).get_json()


def test_new_item_gets_one_holding_mirroring_its_placement(auth_client):
    loc = _loc(auth_client, "Kitchen")
    b = _bin(auth_client, "Drawer", loc["id"])
    it = _item(auth_client, name="AA", quantity=8, binId=b["id"])
    assert it["placementCount"] == 1
    assert it["holdings"][0]["quantity"] == 8
    assert it["holdings"][0]["bin"]["id"] == b["id"]


def test_add_placement_sums_total_and_appears_in_both_bins(auth_client):
    loc = _loc(auth_client, "Kitchen")
    b1, b2 = _bin(auth_client, "Drawer", loc["id"]), _bin(auth_client, "Garage", loc["id"])
    it = _item(auth_client, name="AA", quantity=8, binId=b1["id"])

    r = auth_client.post(f"/api/v1/items/{it['id']}/holdings",
                         json={"binId": b2["id"], "quantity": 12}).get_json()

    assert r["quantity"] == 20 and r["placementCount"] == 2
    b1_items = auth_client.get(f"/api/v1/bins/{b1['id']}").get_json()["items"]
    b2_items = auth_client.get(f"/api/v1/bins/{b2['id']}").get_json()["items"]
    assert any(i["name"] == "AA" and i["quantityHere"] == 8 for i in b1_items)
    assert any(i["name"] == "AA" and i["quantityHere"] == 12 for i in b2_items)


def test_move_partial_conserves_total_and_splits(auth_client):
    loc = _loc(auth_client, "K")
    b1, b2 = _bin(auth_client, "A", loc["id"]), _bin(auth_client, "B", loc["id"])
    it = _item(auth_client, name="AA", quantity=10, binId=b1["id"])

    r = auth_client.post(f"/api/v1/holdings/{it['holdings'][0]['id']}/move",
                         json={"toBinId": b2["id"], "quantity": 4}).get_json()

    assert r["quantity"] == 10  # total conserved
    assert {h["bin"]["name"]: h["quantity"] for h in r["holdings"]} == {"A": 6, "B": 4}


def test_delete_last_placement_returns_422(auth_client):
    loc = _loc(auth_client, "K")
    b = _bin(auth_client, "A", loc["id"])
    it = _item(auth_client, name="AA", quantity=3, binId=b["id"])
    assert auth_client.delete(
        f"/api/v1/holdings/{it['holdings'][0]['id']}").status_code == 422


def test_editing_item_quantity_syncs_the_single_placement(auth_client):
    loc = _loc(auth_client, "K")
    b = _bin(auth_client, "A", loc["id"])
    it = _item(auth_client, name="AA", quantity=3, binId=b["id"])
    r = auth_client.patch(f"/api/v1/items/{it['id']}", json={"quantity": 7}).get_json()
    assert r["quantity"] == 7 and r["holdings"][0]["quantity"] == 7


def test_holding_of_another_group_returns_404(auth_client, client):
    loc = _loc(auth_client, "K")
    b = _bin(auth_client, "A", loc["id"])
    it = _item(auth_client, name="AA", quantity=3, binId=b["id"])
    hid = it["holdings"][0]["id"]

    client.post("/api/v1/users/register",
                json={"email": "b@b.com", "password": "password", "name": "B"})
    tok = client.post("/api/v1/users/login",
                      json={"username": "b@b.com", "password": "password"}).get_json()["token"]
    r = client.put(f"/api/v1/holdings/{hid}", json={"quantity": 99},
                   headers={"Authorization": tok})
    assert r.status_code == 404


def test_migration_backfills_holding_for_legacy_item(app):
    from app import _migrate
    from app.models import Item, Group
    from app.extensions import db
    with app.app_context():
        g = Group(name="H")
        db.session.add(g)
        db.session.flush()
        it = Item(name="Legacy", quantity=5, group_id=g.id)
        db.session.add(it)
        db.session.commit()
        assert len(it.holdings) == 0

        _migrate(app)
        db.session.refresh(it)
        assert len(it.holdings) == 1 and it.holdings[0].quantity == 5

        _migrate(app)  # idempotent — no second holding
        db.session.refresh(it)
        assert len(it.holdings) == 1


def test_add_placement_with_equal_quantity_does_not_crash(auth_client):
    """Regression: a tie on quantity used to 500 (primary tie-break on unflushed
    id=None). Adding a second placement of the same quantity must work."""
    loc = _loc(auth_client, "K")
    b1, b2 = _bin(auth_client, "A", loc["id"]), _bin(auth_client, "B", loc["id"])
    it = _item(auth_client, name="AA", quantity=1, binId=b1["id"])
    r = auth_client.post(f"/api/v1/items/{it['id']}/holdings",
                         json={"binId": b2["id"], "quantity": 1})
    assert r.status_code == 201 and r.get_json()["quantity"] == 2


def test_move_even_split_does_not_crash(auth_client):
    """Regression: splitting qty 2 into 1+1 ties, which used to 500."""
    loc = _loc(auth_client, "K")
    b1, b2 = _bin(auth_client, "A", loc["id"]), _bin(auth_client, "B", loc["id"])
    it = _item(auth_client, name="AA", quantity=2, binId=b1["id"])
    r = auth_client.post(f"/api/v1/holdings/{it['holdings'][0]['id']}/move",
                         json={"toBinId": b2["id"], "quantity": 1})
    assert r.status_code == 200
    assert {h["bin"]["name"]: h["quantity"] for h in r.get_json()["holdings"]} == {"A": 1, "B": 1}
