"""Undoing an item merge — the safety net for the Duplicates view's one
destructive action.

The merge deletes the source row, so the merge response carries an ``undo``
payload: a snapshot of the source in the exact shape POST /items accepts, plus
the ids of the holdings/attachments/maintenance/checkout rows that were MOVED to
the keeper. POST /items/undo-merge recreates the source and moves those same
rows back (append-only re-parenting — the collections cascade delete-orphan), so
history is restored, not duplicated. A stale or replayed payload gets a 409,
never a crash; a cross-group payload is refused like any foreign item.
"""
import io

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
       b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _merge(c, keep_id, source_id):
    r = c.post(f"/api/v1/items/{keep_id}/merge", json={"sourceId": source_id})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_undo_restores_quantities_placements_labels_and_attachments(auth_client):
    kitchen, garage = _loc(auth_client, "Kitchen"), _loc(auth_client, "Garage")
    lab = auth_client.post("/api/v1/labels", json={"name": "power"}).get_json()
    keep = _item(auth_client, "AA batteries", quantity=6, locationId=kitchen["id"])
    dupe = _item(auth_client, "AA batteries", quantity=4, locationId=garage["id"],
                 minQuantity=2, notes="garage stash")
    auth_client.patch(f"/api/v1/items/{dupe['id']}", json={"labelIds": [lab["id"]]})
    auth_client.post(f"/api/v1/items/{dupe['id']}/attachments",
                     data={"file": (io.BytesIO(PNG), "p.png"), "type": "photo",
                           "name": "p.png"}, content_type="multipart/form-data")

    merged = _merge(auth_client, keep["id"], dupe["id"])
    assert "undo" in merged, "merge response carries no undo payload"

    r = auth_client.post("/api/v1/items/undo-merge", json=merged["undo"])
    assert r.status_code == 201, r.get_data(as_text=True)
    restored = r.get_json()

    # The source is back: quantity from its holding, placement, labels, photo.
    assert restored["name"] == "AA batteries"
    assert restored["quantity"] == 4, "quantity did not travel back"
    assert restored["placementCount"] == 1
    assert restored["location"]["id"] == garage["id"], "placement not restored"
    assert [lb["name"] for lb in restored["labels"]] == ["power"]
    assert len(restored["attachments"]) == 1, "the photo did not travel back"
    assert restored["minQuantity"] == 2
    assert restored["notes"] == "garage stash"

    # ...and the keeper is back to its own numbers.
    got = auth_client.get(f"/api/v1/items/{keep['id']}").get_json()
    assert got["quantity"] == 6, "keeper still holds the source's quantity"
    assert got["placementCount"] == 1
    assert len(got["attachments"]) == 0, "photo duplicated onto the keeper"


def test_undo_after_keeper_deleted_is_409(auth_client):
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA batteries", quantity=4)
    merged = _merge(auth_client, keep["id"], dupe["id"])
    auth_client.delete(f"/api/v1/items/{keep['id']}")

    r = auth_client.post("/api/v1/items/undo-merge", json=merged["undo"])
    assert r.status_code == 409, r.get_data(as_text=True)
    assert "error" in r.get_json()


def test_undo_twice_is_409_not_a_duplicate(auth_client):
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA batteries", quantity=4)
    merged = _merge(auth_client, keep["id"], dupe["id"])

    assert auth_client.post("/api/v1/items/undo-merge",
                            json=merged["undo"]).status_code == 201
    r = auth_client.post("/api/v1/items/undo-merge", json=merged["undo"])
    assert r.status_code == 409, "a replayed undo minted a duplicate item"


def test_cross_group_undo_payload_refused(auth_client, app):
    keep = _item(auth_client, "AA batteries", quantity=6)
    dupe = _item(auth_client, "AA batteries", quantity=4)
    merged = _merge(auth_client, keep["id"], dupe["id"])

    other = app.test_client()
    other.post("/api/v1/users/register",
               json={"email": "b@b.com", "password": "password", "name": "B"})
    tok = other.post("/api/v1/users/login",
                     json={"email": "b@b.com",
                           "password": "password"}).get_json()["token"]
    other.environ_base["HTTP_AUTHORIZATION"] = tok

    r = other.post("/api/v1/items/undo-merge", json=merged["undo"])
    assert r.status_code == 404, "another household replayed our undo payload"
