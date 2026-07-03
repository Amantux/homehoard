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
