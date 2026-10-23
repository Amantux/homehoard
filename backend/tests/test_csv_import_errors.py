"""Malformed CSV uploads get a curated 422 and import nothing (was a 500)."""
import io

from app.services import csv_io


def _upload(client, raw: bytes):
    return client.post(
        "/api/v1/items/import",
        data={"file": (io.BytesIO(raw), "a.csv")},
        content_type="multipart/form-data",
    )


def _count(client):
    return len(client.get("/api/v1/items").get_json()["items"])


def test_non_utf8_file_is_422(auth_client):
    r = _upload(auth_client, b"HB.name\ncaf\xe9\n")
    assert r.status_code == 422
    assert r.get_json()["error"] == "file is not UTF-8 text"
    assert _count(auth_client) == 0


def test_nul_byte_is_422(auth_client):
    r = _upload(auth_client, b"HB.name\nok\x00nul\n")
    assert r.status_code == 422
    assert "NUL" in r.get_json()["error"]
    assert _count(auth_client) == 0


def test_oversized_field_is_422_and_imports_nothing(auth_client):
    raw = b"HB.name,HB.description\nGood,x\nA," + b"x" * 200000 + b"\n"
    r = _upload(auth_client, raw)
    assert r.status_code == 422
    assert r.get_json()["error"].startswith("malformed CSV:")
    assert _count(auth_client) == 0


def test_row_cap_is_422_and_imports_nothing(auth_client):
    rows = "HB.name\n" + "".join(f"i{n}\n" for n in range(csv_io.MAX_IMPORT_ROWS + 1))
    r = _upload(auth_client, rows.encode())
    assert r.status_code == 422
    assert r.get_json()["error"] == "too many rows (max 10000)"
    assert _count(auth_client) == 0


def test_json_body_shapes_are_422(auth_client):
    for body in ([1], {"data": {"a": 1}}, {"data": 5}):
        r = auth_client.post("/api/v1/items/import", json=body)
        assert r.status_code == 422, body


def test_valid_csv_still_imports(auth_client):
    r = _upload(auth_client, b"HB.name\nHammer\n")
    assert r.status_code == 201
    assert _count(auth_client) == 1
