"""POST /items must accept the same fields PUT /items/<id> does.

create_item only ever set name/description/quantity/barcode/location/bin, so a
client that sent parentId, syncChildLocations, serialNumber, purchasePrice,
labels, warranty dates… had them silently DROPPED and had to follow up with a
PUT. Silent partial creates are worse than a rejection: the caller gets a 201
and believes the data is stored.
"""


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
