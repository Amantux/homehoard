"""Merging duplicate items — the backend for the Duplicates view.

Two same-named items split quantities, thresholds and history between them.
The merge folds one item into another: holdings MOVE (placements preserved,
quantity handled by resync), labels union, attachments/maintenance/checkout
history carry over, and the source is deleted. Group-scoped and vault-guarded
like every item read.
"""
from app.extensions import db
from app.models import Item


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def test_merge_sums_quantities_and_keeps_both_placements(auth_client):
    kitchen, garage = _loc(auth_client, "Kitchen"), _loc(auth_client, "Garage")
    keep = _item(auth_client, "AA batteries", quantity=6, locationId=kitchen["id"])
    dupe = _item(auth_client, "AA batteries", quantity=4, locationId=garage["id"])

    r = auth_client.post(f"/api/v1/items/{keep['id']}/merge",
                         json={"sourceId": dupe["id"]})

    assert r.status_code == 200, r.get_data(as_text=True)
    got = auth_client.get(f"/api/v1/items/{keep['id']}").get_json()
    assert got["quantity"] == 10, "quantities did not sum"
    assert got["placementCount"] == 2, "the source's placement was lost"
    assert auth_client.get(f"/api/v1/items/{dupe['id']}").status_code == 404


def test_merge_unions_labels_and_carries_attachments(auth_client):
    lab = auth_client.post("/api/v1/labels", json={"name": "power"}).get_json()
    keep = _item(auth_client, "AA batteries", quantity=1)
    dupe = _item(auth_client, "AA batteries", quantity=1)
    auth_client.patch(f"/api/v1/items/{dupe['id']}", json={"labelIds": [lab["id"]]})
    import io
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
           b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
           b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    auth_client.post(f"/api/v1/items/{dupe['id']}/attachments",
                     data={"file": (io.BytesIO(png), "p.png"), "type": "photo",
                           "name": "p.png"}, content_type="multipart/form-data")

    auth_client.post(f"/api/v1/items/{keep['id']}/merge",
                     json={"sourceId": dupe["id"]})

    got = auth_client.get(f"/api/v1/items/{keep['id']}").get_json()
    assert [lb["name"] for lb in got["labels"]] == ["power"]
    assert len(got["attachments"]) == 1, "the photo was lost in the merge"


def test_merge_refuses_cross_group_and_self(auth_client, app):
    keep = _item(auth_client, "AA batteries")
    assert auth_client.post(f"/api/v1/items/{keep['id']}/merge",
                            json={"sourceId": keep["id"]}).status_code == 422

    other = app.test_client()
    other.post("/api/v1/users/register",
               json={"email": "b@b.com", "password": "password", "name": "B"})
    tok = other.post("/api/v1/users/login",
                     json={"email": "b@b.com", "password": "password"}).get_json()["token"]
    other.environ_base["HTTP_AUTHORIZATION"] = tok
    foreign = other.post("/api/v1/items", json={"name": "Theirs"}).get_json()

    r = auth_client.post(f"/api/v1/items/{keep['id']}/merge",
                         json={"sourceId": foreign["id"]})
    assert r.status_code == 404, "merged another household's item"


def test_merge_respects_the_vault(auth_client, app):
    keep = _item(auth_client, "AA batteries")
    hidden = _item(auth_client, "AA batteries")
    with app.app_context():
        db.session.get(Item, hidden["id"]).hidden = True
        db.session.commit()

    r = auth_client.post(f"/api/v1/items/{keep['id']}/merge",
                         json={"sourceId": hidden["id"]})

    assert r.status_code == 404, "a locked session reached a hidden item via merge"
