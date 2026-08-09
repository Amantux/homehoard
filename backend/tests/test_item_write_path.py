"""Creating and updating an item go through ONE writer.

They did not: create silently dropped parentId, syncChildLocations,
identification, price and warranty fields behind a 201, and the sync flag itself
did nothing when a container moved. Both halves live here because the fix was to
make create and update share `_apply` — so a regression in either shows up next
to the other.
"""


# ---- create accepts everything update does ----

def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _item(c, **kw):
    return c.post("/api/v1/items", json=kw)


def _get(c, item_id):
    return c.get(f"/api/v1/items/{item_id}").get_json()


def test_create_honours_parent_and_sync_flag(auth_client):
    loc = _loc(auth_client, "Garage")
    parent = _item(auth_client, name="Toolbox", locationId=loc["id"]).get_json()

    child = _item(auth_client, name="Drill", locationId=loc["id"],
                  parentId=parent["id"], syncChildLocations=True).get_json()

    got = _get(auth_client, child["id"])
    # item_out nests the parent as an object (there is no flat parentId).
    assert (got.get("parent") or {}).get("id") == parent["id"], \
        "parentId dropped on create"
    assert got.get("syncChildLocations") is True, "syncChildLocations dropped"


def test_create_honours_identification_and_money(auth_client):
    it = _item(auth_client, name="Drill", serialNumber="SN-1", modelNumber="M-2",
               manufacturer="Acme", purchasePrice="19.99", insured=True,
               notes="in the blue case").get_json()

    got = _get(auth_client, it["id"])
    assert got["serialNumber"] == "SN-1"
    assert got["modelNumber"] == "M-2"
    assert got["manufacturer"] == "Acme"
    assert got["insured"] is True
    assert got["notes"] == "in the blue case"
    assert float(got["purchasePrice"]) == 19.99


def test_create_honours_warranty_fields(auth_client):
    it = _item(auth_client, name="Laptop", lifetimeWarranty=True,
               warrantyDetails="accidental damage").get_json()

    got = _get(auth_client, it["id"])
    assert got["lifetimeWarranty"] is True
    assert got["warrantyDetails"] == "accidental damage"


def test_create_still_validates_quantity(auth_client):
    """The shared path must not weaken the hostile-input guards."""
    assert _item(auth_client, name="Bad", quantity=-1).status_code == 422
    assert _item(auth_client, name="Bad", quantity="abc").status_code == 422


def test_create_rejects_another_groups_parent(auth_client, app):
    """IDOR: a parent id from another household must not attach."""
    other = app.test_client()
    other.post("/api/v1/users/register",
               json={"email": "b@b.com", "password": "password", "name": "B"})
    tok = other.post("/api/v1/users/login",
                     json={"username": "b@b.com", "password": "password"}
                     ).get_json()["token"]
    other.environ_base["HTTP_AUTHORIZATION"] = tok
    foreign = other.post("/api/v1/items", json={"name": "Theirs"}).get_json()

    mine = _item(auth_client, name="Mine", parentId=foreign["id"])

    # 404 (the shared _require_owned answer — don't confirm it exists) is the
    # expected outcome; a 201 is only acceptable if the parent was NOT attached.
    assert mine.status_code in (201, 404, 422)
    if mine.status_code == 201:
        assert _get(auth_client, mine.get_json()["id"]).get("parent") is None, \
            "attached to another household's item"


# ---- a synced container drags its children ----

def _made(c, **kw):
    """The created item's JSON — for tests that only care about the result.
    (`_item` returns the raw response, because other tests assert status_code.)"""
    return c.post("/api/v1/items", json=kw).get_json()


def _put(c, item_id, **body):
    return c.put(f"/api/v1/items/{item_id}", json=body)


def _where(c, item_id):
    loc = c.get(f"/api/v1/items/{item_id}").get_json().get("location")
    return loc["id"] if loc else None


def test_moving_a_synced_parent_moves_its_children(auth_client):
    a, b = _loc(auth_client, "Garage"), _loc(auth_client, "Attic")
    parent = _made(auth_client, name="Toolbox", locationId=a["id"])
    child = _made(auth_client, name="Drill", locationId=a["id"])
    _put(auth_client, parent["id"], syncChildLocations=True)
    _put(auth_client, child["id"], parentId=parent["id"])

    _put(auth_client, parent["id"], locationId=b["id"])

    assert _where(auth_client, child["id"]) == b["id"], "child did not follow parent"


def test_the_move_is_durable_through_a_later_resync(auth_client):
    """ItemHolding is the placement source of truth and item.location_id only
    mirrors the primary holding — so the cascade must move the HOLDING, or the
    next edit (which resyncs from holdings) reverts the child to its old spot."""
    a, b = _loc(auth_client, "Garage"), _loc(auth_client, "Attic")
    parent = _made(auth_client, name="Toolbox", locationId=a["id"])
    child = _made(auth_client, name="Drill", locationId=a["id"])
    _put(auth_client, parent["id"], syncChildLocations=True)
    _put(auth_client, child["id"], parentId=parent["id"])
    _put(auth_client, parent["id"], locationId=b["id"])

    # an unrelated edit on the child triggers resync_item from its holdings
    _put(auth_client, child["id"], name="Drill 2")

    assert _where(auth_client, child["id"]) == b["id"], "move reverted on resync"


def test_grandchildren_follow_when_the_chain_is_synced(auth_client):
    a, b = _loc(auth_client, "L1"), _loc(auth_client, "L2")
    p = _made(auth_client, name="P", locationId=a["id"])
    c = _made(auth_client, name="C", locationId=a["id"])
    g = _made(auth_client, name="G", locationId=a["id"])
    _put(auth_client, p["id"], syncChildLocations=True)
    _put(auth_client, c["id"], parentId=p["id"], syncChildLocations=True)
    _put(auth_client, g["id"], parentId=c["id"])

    _put(auth_client, p["id"], locationId=b["id"])

    assert _where(auth_client, g["id"]) == b["id"], "grandchild did not follow"


def test_unsynced_parent_leaves_children_put(auth_client):
    a, b = _loc(auth_client, "Shed"), _loc(auth_client, "Basement")
    parent = _made(auth_client, name="Crate", locationId=a["id"])
    child = _made(auth_client, name="Widget", locationId=a["id"])
    _put(auth_client, child["id"], parentId=parent["id"])   # linked, but no flag

    _put(auth_client, parent["id"], locationId=b["id"])

    assert _where(auth_client, child["id"]) == a["id"], "child moved without the flag"
