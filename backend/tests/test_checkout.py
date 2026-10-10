def test_checkout_and_checkin(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()
    assert item["checkedOut"] is False

    out = auth_client.post(
        f"/api/v1/items/{item['id']}/checkout",
        json={"person": "Alex", "due": "2026-07-10", "notes": "for the deck"},
    ).get_json()
    assert out["checkedOut"] is True
    assert out["checkedOutTo"] == "Alex"
    assert out["checkoutDue"].startswith("2026-07-10")

    # Double checkout is rejected.
    dup = auth_client.post(f"/api/v1/items/{item['id']}/checkout", json={"person": "Bo"})
    assert dup.status_code == 409

    back = auth_client.post(f"/api/v1/items/{item['id']}/checkin", json={}).get_json()
    assert back["checkedOut"] is False
    assert back["checkedOutTo"] == ""
    assert len(back["checkoutHistory"]) == 2  # out + in

    # Check-in when already in is rejected.
    assert auth_client.post(f"/api/v1/items/{item['id']}/checkin", json={}).status_code == 409


def test_checkout_then_add_details(auth_client):
    """Instant checkout (empty body) followed by PATCHing the details in."""
    item = auth_client.post("/api/v1/items", json={"name": "Saw"}).get_json()

    # One-click checkout — no details yet.
    out = auth_client.post(f"/api/v1/items/{item['id']}/checkout", json={}).get_json()
    assert out["checkedOut"] is True
    assert out["checkedOutTo"] == ""

    # Add the details afterwards.
    upd = auth_client.patch(
        f"/api/v1/items/{item['id']}/checkout",
        json={"person": "Alex", "due": "2026-07-10", "notes": "for the deck"},
    ).get_json()
    assert upd["checkedOutTo"] == "Alex"
    assert upd["checkoutDue"].startswith("2026-07-10")
    latest_out = next(h for h in upd["checkoutHistory"] if h["action"] == "out")
    assert latest_out["person"] == "Alex"
    assert latest_out["notes"] == "for the deck"

    # Patching when the item isn't checked out is rejected.
    auth_client.post(f"/api/v1/items/{item['id']}/checkin", json={})
    assert auth_client.patch(
        f"/api/v1/items/{item['id']}/checkout", json={"person": "Bo"}
    ).status_code == 409


def test_checkouts_list(auth_client):
    a = auth_client.post("/api/v1/items", json={"name": "A"}).get_json()
    auth_client.post("/api/v1/items", json={"name": "B"})
    auth_client.post(f"/api/v1/items/{a['id']}/checkout", json={"person": "Sam"})

    res = auth_client.get("/api/v1/checkouts").get_json()
    assert res["total"] == 1
    assert res["items"][0]["name"] == "A"
    assert res["items"][0]["checkedOutTo"] == "Sam"


def test_checkout_overdue_flag(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Ladder"}).get_json()
    auth_client.post(
        f"/api/v1/items/{item['id']}/checkout",
        json={"person": "Kim", "due": "2020-01-01"},
    )
    res = auth_client.get("/api/v1/checkouts").get_json()
    assert res["items"][0]["overdue"] is True


def test_checkout_requires_auth(client):
    assert client.get("/api/v1/checkouts").status_code == 401


def test_checkouts_overdue_with_aware_now(auth_client):
    """The list compares naive stored dues against an aware now (as_utc), and
    emits checkedOutAt/checkoutDue with an explicit +00:00 offset."""
    import re
    iso_utc = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00$")
    late = auth_client.post("/api/v1/items", json={"name": "Late"}).get_json()
    fine = auth_client.post("/api/v1/items", json={"name": "Fine"}).get_json()
    zulu = auth_client.post("/api/v1/items", json={"name": "Zulu"}).get_json()
    auth_client.post(f"/api/v1/items/{late['id']}/checkout", json={"due": "2000-01-01"})
    auth_client.post(f"/api/v1/items/{fine['id']}/checkout", json={"due": "2999-01-01"})
    auth_client.post(f"/api/v1/items/{zulu['id']}/checkout",
                     json={"due": "2000-01-01T00:00:00Z"})

    rows = {r["name"]: r for r in auth_client.get("/api/v1/checkouts").get_json()["items"]}
    assert rows["Late"]["overdue"] is True
    assert rows["Zulu"]["overdue"] is True
    assert rows["Fine"]["overdue"] is False
    for r in rows.values():
        assert iso_utc.match(r["checkedOutAt"]), r["checkedOutAt"]
        assert iso_utc.match(r["checkoutDue"]), r["checkoutDue"]
