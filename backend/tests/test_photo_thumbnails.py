"""Photo thumbnails: generated on upload, served via ?thumb=1, backfillable.

A thumbnail is a JPEG (max 400px long edge) written beside the original file at
``<path>.thumb.jpg`` — pure name convention, no schema change. The document
route falls back to the original when no thumbnail exists (pre-existing photos,
non-image files), so ?thumb=1 is always safe to request.
"""
import io
import os

import pytest
from PIL import features

from app.extensions import db
from app.models import Document
from app.services.thumbnails import ALLOWED_FORMATS, thumb_path


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


def _scene():
    """A deterministic, detailed 640x480 image (a flat colour would shrink to nothing)."""
    from PIL import Image

    return Image.effect_mandelbrot((640, 480), (-2.5, -1.5, 1.0, 1.5), 40).convert("RGB")


def _image_bytes(fmt: str, **save_kwargs) -> bytes:
    """A real 640x480 ``fmt`` image, written by Pillow itself."""
    scene = _scene()
    buf = io.BytesIO()
    (scene.convert("P") if fmt == "GIF" else scene).save(buf, fmt, **save_kwargs)
    return buf.getvalue()


def _mpo_bytes() -> bytes:
    """A real two-picture MPO, the multi-picture JPEG some phones write."""
    return _image_bytes("MPO", save_all=True, append_images=[_scene().rotate(180)])


def _exif_rotated_jpeg_bytes() -> bytes:
    """A 640x480 JPEG whose EXIF Orientation=6 says 'display rotated': 480x640."""
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 6
    return _image_bytes("JPEG", exif=exif)


def _decodes_with_no_allowlist(data: bytes, fmt: str) -> None:
    """Assert Pillow, given no allowlist, reads ``data`` as a genuine ``fmt`` image.

    Without this, "no thumbnail" would prove nothing about the allowlist: it could
    just mean the sample was never decodable.
    """
    from PIL import Image

    with Image.open(io.BytesIO(data)) as probe:
        assert probe.format == fmt
        probe.load()


def _upload_photo(app, client, data: bytes, filename: str):
    """Upload ``data`` as a photo. Returns (document id, thumbnail path)."""
    r = _upload(client, _item(client)["id"], data, filename)
    assert r.status_code == 201, r.get_data(as_text=True)
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    return doc_id, thumb_path(_doc_path(app, doc_id))


def _thumb_size(tp: str) -> tuple:
    """Size of the thumbnail at ``tp``, which must exist and be a real JPEG."""
    from PIL import Image

    assert os.path.isfile(tp), f"no thumbnail written beside the original: {tp}"
    with Image.open(tp) as thumb:
        assert thumb.format == "JPEG"
        return thumb.size


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


# --- decoder allowlist (services/thumbnails.py ALLOWED_FORMATS) --------------
# Pillow's Image.open() tries every decoder it ships unless told otherwise, and the
# upload routes take any bytes flagged "photo". Each test below uses a real file
# written by Pillow itself, so none can pass vacuously.


def test_decoder_allowlist_is_exactly_the_household_photo_formats():
    """Widening it is a security decision, so it must be a deliberate edit here.

    The format tests below can't cover every decoder Pillow ships: EPS, for one,
    shells out to Ghostscript to decode, so no sample proves it unreachable.
    """
    assert set(ALLOWED_FORMATS) == {"JPEG", "PNG", "WEBP", "GIF"}


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "GIF"])
def test_every_allowed_photo_format_gets_a_downscaled_jpeg_thumbnail(
        app, auth_client, fmt):
    data = _image_bytes(fmt)
    _decodes_with_no_allowlist(data, fmt)

    _, tp = _upload_photo(app, auth_client, data, f"cam.{fmt.lower()}")

    assert _thumb_size(tp) == (400, 300)  # 640x480 scaled to the 400px long edge


def test_multi_picture_phone_jpeg_gets_a_thumbnail(app, auth_client):
    """MPO has no entry of its own in Pillow's registry: it opens as a JPEG."""
    data = _mpo_bytes()
    _decodes_with_no_allowlist(data, "MPO")

    _, tp = _upload_photo(app, auth_client, data, "burst.jpg")

    assert _thumb_size(tp) == (400, 300)


def test_exif_rotated_jpeg_thumbnail_is_upright(app, auth_client):
    """Stored 640x480 with Orientation=6, so it displays as 480x640 portrait."""
    _, tp = _upload_photo(app, auth_client, _exif_rotated_jpeg_bytes(), "port.jpg")

    assert _thumb_size(tp) == (300, 400)


def test_allowed_format_is_recognised_by_its_bytes_not_its_file_name(app, auth_client):
    """A JPEG named like a TIFF, or with no extension at all, still gets a thumbnail."""
    data = _image_bytes("JPEG")
    _decodes_with_no_allowlist(data, "JPEG")

    for filename in ("scan.tif", "scan.bmp", "scan"):
        _, tp = _upload_photo(app, auth_client, data, filename)

        assert _thumb_size(tp) == (400, 300), filename


@pytest.mark.parametrize("fmt", [
    "BMP", "TIFF", "PCX", "PPM", "TGA", "ICO",
    pytest.param("AVIF", marks=pytest.mark.skipif(
        not features.check("avif"), reason="this Pillow build has no AVIF")),
])
def test_photo_in_a_format_outside_the_allowlist_gets_no_thumbnail_and_still_uploads(
        app, auth_client, fmt):
    """Pillow can decode these, but a household photo doesn't need them.

    Removing ``formats=`` from thumbnails.generate() makes this fail: Pillow then
    decodes the file and writes a thumbnail. The check is on the bytes, not the
    name, so each is also sent named like an allowed format, as a crafted upload
    would be. The upload itself must succeed, and ?thumb=1 must fall back to the
    original.
    """
    data = _image_bytes(fmt)
    _decodes_with_no_allowlist(data, fmt)

    for filename in (f"scan.{fmt.lower()}", "scan.jpg", "scan.png"):
        doc_id, tp = _upload_photo(app, auth_client, data, filename)

        assert not os.path.isfile(tp), (
            f"a {fmt} named {filename} was decoded: decoder allowlist missing")
        got = auth_client.get(f"/api/v1/documents/{doc_id}?thumb=1")
        assert got.status_code == 200
        assert got.data == data


def test_bin_photo_outside_the_allowlist_still_uploads_without_a_thumbnail(
        app, auth_client):
    data = _image_bytes("TIFF")
    _decodes_with_no_allowlist(data, "TIFF")
    loc = auth_client.post("/api/v1/locations", json={"name": "Shed"}).get_json()
    b = auth_client.post("/api/v1/bins",
                         json={"name": "Crate", "locationId": loc["id"]}).get_json()

    r = auth_client.post(
        f"/api/v1/bins/{b['id']}/attachments",
        data={"file": (io.BytesIO(data), "crate.jpg"), "type": "photo",
              "name": "crate.jpg"},
        content_type="multipart/form-data")

    assert r.status_code == 201, r.get_data(as_text=True)
    doc_id = r.get_json()["attachments"][0]["document"]["id"]
    assert not os.path.isfile(thumb_path(_doc_path(app, doc_id))), (
        "a TIFF was decoded: decoder allowlist missing")


def test_backfill_leaves_a_photo_outside_the_allowlist_without_a_thumbnail(
        app, auth_client):
    data = _image_bytes("TIFF")
    _decodes_with_no_allowlist(data, "TIFF")
    _, tp = _upload_photo(app, auth_client, data, "scan.tif")

    first = auth_client.post("/api/v1/actions/generate-thumbnails")
    second = auth_client.post("/api/v1/actions/generate-thumbnails")

    assert first.status_code == 200
    assert first.get_json() == {"generated": 0, "skipped": 1}
    assert second.get_json() == {"generated": 0, "skipped": 1}
    assert not os.path.isfile(tp), "a TIFF was decoded: decoder allowlist missing"
