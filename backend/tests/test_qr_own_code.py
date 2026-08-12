"""Linking a code you already own is the primary path in the QR panel.

The panel now shows the "scan or type your code" field unconditionally and puts
generating a HomeHoard QR behind a disclosure, so these pin what that field
posts — including the duplicate-code error, whose WORDING the UI keys off to
show "That code is already assigned to something else" instead of a raw message.
"""


def _item(c, name="Drill"):
    return c.post("/api/v1/items", json={"name": name}).get_json()


def _link_own(c, item, code, fmt="barcode"):
    return c.post("/api/v1/qr-tags", json={
        "kind": "item", "targetId": item["id"], "source": "external",
        "code": code, "codeFormat": fmt})


def test_an_existing_code_can_be_linked_without_generating_anything(auth_client):
    item = _item(auth_client)

    r = _link_own(auth_client, item, "ABC-123", "code128")

    assert r.status_code in (200, 201), r.get_data(as_text=True)
    tag = r.get_json()
    assert tag["source"] == "external"
    assert tag["code"] == "ABC-123"
    assert tag["codeFormat"] == "code128"


def test_a_linked_code_resolves_by_scanning_it(auth_client):
    """The point of linking: scanning your own label finds the item."""
    item = _item(auth_client)
    _link_own(auth_client, item, "MY-LABEL-9")

    found = auth_client.get("/api/v1/barcode/MY-LABEL-9").get_json()

    assert found["status"] == "registered"
    assert found["targetId"] == item["id"]


def test_reusing_a_code_is_refused_with_the_wording_the_ui_matches(auth_client):
    """The panel shows a friendly message when the error says 'already'. If the
    server's wording changes, that check silently degrades to a raw error."""
    a, b = _item(auth_client, "Drill"), _item(auth_client, "Saw")
    _link_own(auth_client, a, "DUP-1")

    r = _link_own(auth_client, b, "DUP-1")

    assert r.status_code >= 400
    assert "already" in r.get_json()["error"].lower()


def test_generating_still_works_and_is_a_different_source(auth_client):
    """Generating moved behind a disclosure in the UI; the endpoint is unchanged."""
    item = _item(auth_client)

    r = auth_client.post("/api/v1/qr-tags", json={
        "kind": "item", "targetId": item["id"], "description": "lid"})

    assert r.status_code in (200, 201)
    assert r.get_json()["source"] == "generated"
