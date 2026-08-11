"""Creating an item inside a bin, with a photo, in one go.

The bin page stages a photo and uploads it right after the item exists (an
attachment needs an item id). These pin the two-request contract that flow
depends on, including the bit that makes it worth doing: the first photo becomes
the item's PRIMARY image, so it shows as the thumbnail in the bin.
"""
import io


def _bin(c, name="Crate"):
    loc = c.post("/api/v1/locations", json={"name": "Shed"}).get_json()
    return c.post("/api/v1/bins", json={"name": name, "locationId": loc["id"]}).get_json()


def _png():
    # smallest valid PNG — enough for the server's image handling
    return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def test_item_created_in_a_bin_accepts_a_photo_that_becomes_its_thumbnail(auth_client):
    b = _bin(auth_client)

    item = auth_client.post("/api/v1/items",
                            json={"name": "Drill", "quantity": 1,
                                  "binId": b["id"]}).get_json()
    r = auth_client.post(
        f"/api/v1/items/{item['id']}/attachments",
        data={"file": (io.BytesIO(_png()), "drill.png"),
              "type": "photo", "name": "drill.png"},
        content_type="multipart/form-data")

    assert r.status_code in (200, 201), r.get_data(as_text=True)
    atts = r.get_json()["attachments"]
    assert len(atts) == 1
    assert atts[0]["primary"] is True, "the first photo must become the thumbnail"

    # and it is in the bin, with the photo, on the page the user is looking at
    listed = auth_client.get(f"/api/v1/bins/{b['id']}").get_json()["items"]
    assert [i["name"] for i in listed] == ["Drill"]
    assert listed[0].get("imageId"), "the bin listing has no thumbnail for it"


def test_a_failed_photo_upload_leaves_the_item_in_place(auth_client):
    """The UI reports 'created, but the photo didn't upload' — that message is
    only honest if the item really does survive a rejected upload."""
    b = _bin(auth_client)
    item = auth_client.post("/api/v1/items",
                            json={"name": "Drill", "binId": b["id"]}).get_json()

    bad = auth_client.post(f"/api/v1/items/{item['id']}/attachments",
                           data={}, content_type="multipart/form-data")

    assert bad.status_code >= 400
    listed = auth_client.get(f"/api/v1/bins/{b['id']}").get_json()["items"]
    assert [i["name"] for i in listed] == ["Drill"], "the item vanished with the upload"
