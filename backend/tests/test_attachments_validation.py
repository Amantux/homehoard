"""Attachment label validation and missing-file handling."""
import io
import os


def _item(c):
    return c.post("/api/v1/items", json={"name": "Drill", "quantity": 1}).get_json()


def _upload(c, item, **form):
    data = {"file": (io.BytesIO(b"hello"), "a.txt"), **form}
    return c.post(f"/api/v1/items/{item['id']}/attachments", data=data,
                  content_type="multipart/form-data")


def _att(c, item):
    r = _upload(c, item)
    assert r.status_code == 201
    return r.get_json()["attachments"][0]


def test_upload_rejects_unknown_type(auth_client):
    assert _upload(auth_client, _item(auth_client), type="bogus").status_code == 422


def test_update_rejects_unknown_and_non_string_type(auth_client):
    item = _item(auth_client)
    a = _att(auth_client, item)
    url = f"/api/v1/items/{item['id']}/attachments/{a['id']}"
    assert auth_client.put(url, json={"type": "bogus"}).status_code == 422
    assert auth_client.put(url, json={"type": {"a": 1}}).status_code == 422
    assert auth_client.put(url, json={"type": "photo"}).status_code == 200


def test_update_rejects_long_title(auth_client):
    item = _item(auth_client)
    a = _att(auth_client, item)
    url = f"/api/v1/items/{item['id']}/attachments/{a['id']}"
    assert auth_client.put(url, json={"title": "x" * 300}).status_code == 422
    assert auth_client.put(url, json={"title": "x" * 200}).status_code == 200


def test_upload_rejects_long_name(auth_client):
    assert _upload(auth_client, _item(auth_client), name="x" * 300).status_code == 422


def test_download_of_missing_file_is_404(auth_client, app):
    from app.extensions import db
    from app.models import Attachment
    item = _item(auth_client)
    a = _att(auth_client, item)
    with app.app_context():
        os.remove(db.session.get(Attachment, a["id"]).document.path)
    r = auth_client.get(f"/api/v1/items/{item['id']}/attachments/{a['id']}")
    assert r.status_code == 404
    assert "no longer on disk" in r.get_json()["error"]
