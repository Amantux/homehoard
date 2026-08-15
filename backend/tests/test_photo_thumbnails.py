"""Photo thumbnails: generated on upload, served via ?thumb=1, backfillable.

A thumbnail is a JPEG (max 400px long edge) written beside the original file at
``<path>.thumb.jpg`` — pure name convention, no schema change. The document
route falls back to the original when no thumbnail exists (pre-existing photos,
non-image files), so ?thumb=1 is always safe to request.
"""
import io
import os

from app.extensions import db
from app.models import Document
from app.services.thumbnails import thumb_path


def _big_png() -> bytes:
    """A real 800x600 PNG, large enough that a 400px thumbnail must be smaller."""
    from PIL import Image

    import random

    rng = random.Random(42)  # seeded: deterministic test data
    im = Image.new("RGB", (800, 600))
    # Incompressible noise, so the full-size PNG is genuinely big and the
    # 400px JPEG thumbnail is guaranteed smaller (as with a real photo).
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(800 * 600)])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _upload(client, item_id, data: bytes, filename: str, atype="photo"):
    return client.post(
        f"/api/v1/items/{item_id}/attachments",
        data={"file": (io.BytesIO(data), filename), "type": atype,
              "name": filename},
        content_type="multipart/form-data")


def _item(client, name="Camera"):
    return client.post("/api/v1/items", json={"name": name}).get_json()


def _doc_path(app, document_id: str) -> str:
    with app.app_context():
        return db.session.get(Document, document_id).path


def test_photo_upload_creates_smaller_jpeg_thumbnail_beside_original(app, auth_client):
    item = _item(auth_client)

    r = _upload(auth_client, item["id"], _big_png(), "cam.png")

    assert r.status_code == 201, r.get_data(as_text=True)
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    path = _doc_path(app, doc_id)
    tp = thumb_path(path)
    assert os.path.isfile(tp), "no thumbnail written beside the original"
    assert os.path.getsize(tp) < os.path.getsize(path)
    with open(tp, "rb") as f:
        assert f.read(2) == b"\xff\xd8", "thumbnail is not a JPEG"


def test_document_thumb_param_serves_the_thumbnail(auth_client):
    item = _item(auth_client)
    original = _big_png()
    doc_id = _upload(auth_client, item["id"], original,
                     "cam.png").get_json()["attachments"][0]["document"]["id"]

    full = auth_client.get(f"/api/v1/documents/{doc_id}")
    thumb = auth_client.get(f"/api/v1/documents/{doc_id}?thumb=1")

    assert full.status_code == thumb.status_code == 200
    assert thumb.content_type.startswith("image/jpeg")
    assert len(thumb.data) < len(full.data)
    assert full.data == original


def test_bin_photo_upload_creates_thumbnail(app, auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Shed"}).get_json()
    b = auth_client.post("/api/v1/bins",
                         json={"name": "Crate", "locationId": loc["id"]}).get_json()

    r = auth_client.post(
        f"/api/v1/bins/{b['id']}/attachments",
        data={"file": (io.BytesIO(_big_png()), "crate.png"), "type": "photo",
              "name": "crate.png"},
        content_type="multipart/form-data")

    assert r.status_code == 201, r.get_data(as_text=True)
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    assert os.path.isfile(thumb_path(_doc_path(app, doc_id)))


def test_thumb_param_falls_back_to_original_when_no_thumbnail(app, auth_client):
    """Pre-existing photos have no thumbnail file — ?thumb=1 must still work."""
    item = _item(auth_client)
    original = _big_png()
    doc_id = _upload(auth_client, item["id"], original,
                     "old.png").get_json()["attachments"][0]["document"]["id"]
    os.remove(thumb_path(_doc_path(app, doc_id)))  # simulate a pre-pipeline photo

    r = auth_client.get(f"/api/v1/documents/{doc_id}?thumb=1")

    assert r.status_code == 200
    assert r.data == original


def test_non_image_attachment_gets_no_thumbnail_and_still_downloads(app, auth_client):
    item = _item(auth_client)

    r = _upload(auth_client, item["id"], b"just some text\n", "manual.txt",
                atype="attachment")

    assert r.status_code == 201
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    assert not os.path.isfile(thumb_path(_doc_path(app, doc_id)))
    got = auth_client.get(f"/api/v1/documents/{doc_id}?thumb=1")
    assert got.status_code == 200
    assert got.data == b"just some text\n"


def test_non_image_uploaded_as_photo_does_not_fail_the_upload(app, auth_client):
    """A text file mislabeled type=photo: no thumbnail, but the upload succeeds."""
    item = _item(auth_client)

    r = _upload(auth_client, item["id"], b"not an image", "fake.jpg")

    assert r.status_code == 201, r.get_data(as_text=True)
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    assert not os.path.isfile(thumb_path(_doc_path(app, doc_id)))


def test_backfill_action_generates_missing_thumbnails_idempotently(app, auth_client):
    item = _item(auth_client)
    doc_id = _upload(auth_client, item["id"], _big_png(),
                     "old.png").get_json()["attachments"][0]["document"]["id"]
    tp = thumb_path(_doc_path(app, doc_id))
    os.remove(tp)  # simulate a photo from before the pipeline existed

    first = auth_client.post("/api/v1/actions/generate-thumbnails")
    second = auth_client.post("/api/v1/actions/generate-thumbnails")

    assert first.status_code == 200
    assert first.get_json()["generated"] == 1
    assert os.path.isfile(tp)
    assert second.get_json()["generated"] == 0, "backfill is not idempotent"


def test_deleting_a_photo_attachment_removes_its_thumbnail(app, auth_client):
    item = _item(auth_client)
    body = _upload(auth_client, item["id"], _big_png(), "cam.png").get_json()
    att = body["attachments"][0]
    tp = thumb_path(_doc_path(app, att["document"]["id"]))
    assert os.path.isfile(tp)

    r = auth_client.delete(f"/api/v1/items/{item['id']}/attachments/{att['id']}")

    assert r.status_code == 204
    assert not os.path.isfile(tp), "orphaned thumbnail left on disk"
