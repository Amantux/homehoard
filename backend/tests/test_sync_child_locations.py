"""sync_child_locations was a dead flag: settable and serialized, but moving a
parent item never moved its children. The model's own promise — 'When set,
moving this item's container moves its children with it' — was unimplemented.

(Links + the flag are set via PUT: create_item does not yet honour parentId /
syncChildLocations — a separate gap, noted, not this fix.)
"""


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _item(c, name, loc_id):
    return c.post("/api/v1/items", json={"name": name, "locationId": loc_id}).get_json()


def _put(c, item_id, **body):
    return c.put(f"/api/v1/items/{item_id}", json=body)


def _where(c, item_id):
    loc = c.get(f"/api/v1/items/{item_id}").get_json().get("location")
    return loc["id"] if loc else None


def test_moving_a_synced_parent_moves_its_children(auth_client):
    a, b = _loc(auth_client, "Garage"), _loc(auth_client, "Attic")
    parent = _item(auth_client, "Toolbox", a["id"])
    child = _item(auth_client, "Drill", a["id"])
    _put(auth_client, parent["id"], syncChildLocations=True)
    _put(auth_client, child["id"], parentId=parent["id"])

    _put(auth_client, parent["id"], locationId=b["id"])

    assert _where(auth_client, child["id"]) == b["id"], "child did not follow parent"


def test_grandchildren_follow_when_the_chain_is_synced(auth_client):
    a, b = _loc(auth_client, "L1"), _loc(auth_client, "L2")
    p = _item(auth_client, "P", a["id"])
    c = _item(auth_client, "C", a["id"])
    g = _item(auth_client, "G", a["id"])
    _put(auth_client, p["id"], syncChildLocations=True)
    _put(auth_client, c["id"], parentId=p["id"], syncChildLocations=True)
    _put(auth_client, g["id"], parentId=c["id"])

    _put(auth_client, p["id"], locationId=b["id"])

    assert _where(auth_client, g["id"]) == b["id"], "grandchild did not follow"


def test_unsynced_parent_leaves_children_put(auth_client):
    a, b = _loc(auth_client, "Shed"), _loc(auth_client, "Basement")
    parent = _item(auth_client, "Crate", a["id"])
    child = _item(auth_client, "Widget", a["id"])
    _put(auth_client, child["id"], parentId=parent["id"])   # linked, but no flag

    _put(auth_client, parent["id"], locationId=b["id"])

    assert _where(auth_client, child["id"]) == a["id"], "child moved without the flag"
