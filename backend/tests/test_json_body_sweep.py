"""P36: every JSON write route reads its body through ``json_body()``.

``request.get_json(force=True) or {}`` handed a list/scalar body straight to
``data.get(...)`` and 500'd. One representative route per module now answers a
``[]`` body with a 422 on ``fields.body``; the scan below fails if the old idiom
comes back anywhere in ``app/api``.
"""
import io
import pathlib

import pytest

from app.api import _validation

H = "/api/v1"
# app/api has no __init__.py (namespace package), so locate it via a module.
API_DIR = pathlib.Path(_validation.__file__).parent


def _item(c):
    return c.post(f"{H}/items", json={"name": "Probe"}).get_json()["id"]


def _attachment(c):
    item_id = _item(c)
    r = c.post(f"{H}/items/{item_id}/attachments",
               data={"file": (io.BytesIO(b"hello"), "a.txt"),
                     "type": "attachment", "name": "a.txt"},
               content_type="multipart/form-data")
    assert r.status_code < 300, r.data[:200]
    return f"{H}/items/{item_id}/attachments/{r.get_json()['attachments'][0]['id']}"


# module -> (method, url builder). Each route reaches json_body() before any
# body-independent validation, so a [] body is the only reason it can fail.
ROUTES = {
    "attachments": ("put", _attachment),
    "bins": ("post", lambda c: f"{H}/bins"),
    "chat": ("post", lambda c: f"{H}/chat"),
    "groups": ("put", lambda c: f"{H}/groups"),
    "holdings": ("post", lambda c: f"{H}/items/{_item(c)}/holdings"),
    "items": ("post", lambda c: f"{H}/items"),
    "labels": ("post", lambda c: f"{H}/labels"),
    "locations": ("post", lambda c: f"{H}/locations"),  # converted in P35
    "maintenance": ("post", lambda c: f"{H}/items/{_item(c)}/maintenance"),
    "misc": ("put", lambda c: f"{H}/settings/chat"),
    "notifiers": ("post", lambda c: f"{H}/notifiers"),
    "qrtags": ("post", lambda c: f"{H}/qr-tags"),
    "tokens": ("post", lambda c: f"{H}/tokens"),
    "users": ("post", lambda c: f"{H}/users/login"),
}


@pytest.mark.parametrize("module", sorted(ROUTES))
def test_list_body_is_a_422_field_error(auth_client, module):
    method, url = ROUTES[module]
    r = getattr(auth_client, method)(url(auth_client), json=[])
    assert r.status_code == 422, (module, r.status_code, r.data[:200])
    assert r.get_json()["fields"] == {"body": "must be a JSON object"}


def test_sweep_covers_every_api_module_that_reads_json():
    """A module that starts calling json_body() must get a case above."""
    pkg = API_DIR
    users = {p.stem for p in pkg.glob("*.py")
             if p.name != "_validation.py" and "json_body()" in p.read_text()}
    assert users <= set(ROUTES), users - set(ROUTES)


def test_no_get_json_force_idiom_left_in_api():
    pkg = API_DIR
    hits = [f"{p.name}:{n}" for p in sorted(pkg.rglob("*.py"))
            if p.name != "_validation.py"
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if "get_json(force=True)" in line]
    assert hits == [], hits
