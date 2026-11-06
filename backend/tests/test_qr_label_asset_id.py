"""The printable QR label sheet prints an item's asset id under its name.

The page (frontend LabelSheet.vue) reads it from GET /qr-tags: an item tag's
`target` is the item summary, whose `assetId` is `_fmt_asset(item.asset_id)`.
An item that has none (imported and legacy rows sit at 0) comes out as
"000-000", and the sheet leaves that off the label (its NO_ASSET_ID) rather than
printing a number that looks real.

Both ends of that contract are pinned here: rename `assetId`, drop it from the
item summary, or change the "no asset id" spelling, and the label sheet would
quietly print nothing or print "000-000". Bins and locations have no asset id.
"""
from app.extensions import db
from app.models import Item
from app.schemas.serializers import _fmt_asset


def _tag(c, kind, target_id):
    r = c.post("/api/v1/qr-tags", json={"kind": kind, "targetId": target_id})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()


def _listed(c, tag_id):
    return next(t for t in c.get("/api/v1/qr-tags").get_json() if t["id"] == tag_id)


def test_asset_id_spelling():
    """The frontend compares against this exact spelling of 'no asset id'."""
    assert _fmt_asset(0) == "000-000"
    assert _fmt_asset(7) == "000-007"
    assert _fmt_asset(1007) == "001-007"


def test_an_item_tag_carries_the_asset_id_the_label_prints(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()
    tag = _tag(auth_client, "item", item["id"])

    target = _listed(auth_client, tag["id"])["target"]

    assert item["assetId"] == "000-001"
    assert target["name"] == "Drill"
    assert target["assetId"] == "000-001"


def test_an_item_with_no_asset_id_is_listed_as_the_zero_spelling(auth_client, app):
    """Imported rows can be left unassigned. The label sheet filters exactly this
    value out, so it must stay what the serializer emits for asset_id == 0."""
    item = auth_client.post("/api/v1/items", json={"name": "Loose screws"}).get_json()
    tag = _tag(auth_client, "item", item["id"])
    with app.app_context():
        db.session.get(Item, item["id"]).asset_id = 0
        db.session.commit()

    target = _listed(auth_client, tag["id"])["target"]

    assert target["assetId"] == "000-000"


def test_bin_and_location_tags_have_no_asset_id(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    bin_ = auth_client.post(
        "/api/v1/bins", json={"name": "Bin A", "locationId": loc["id"]}).get_json()
    bin_tag = _tag(auth_client, "bin", bin_["id"])
    loc_tag = _tag(auth_client, "location", loc["id"])

    assert "assetId" not in _listed(auth_client, bin_tag["id"])["target"]
    assert "assetId" not in _listed(auth_client, loc_tag["id"])["target"]
