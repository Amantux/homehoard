from datetime import datetime, timedelta


def test_summary_shape(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    auth_client.post("/api/v1/bins", json={"name": "Box", "locationId": loc["id"]})
    # An item with a warranty expiring in ~15 days.
    soon = (datetime.utcnow() + timedelta(days=15)).isoformat()
    item = auth_client.post("/api/v1/items", json={"name": "Router"}).get_json()
    auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "Router", "warrantyExpires": soon, "insured": True,
              "purchasePrice": 100, "quantity": 1},
    )

    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["health"] is True
    assert s["totals"]["items"] == 1
    assert s["totals"]["bins"] == 1
    assert s["totals"]["locations"] == 1
    assert s["totals"]["insuredValue"] == 100
    assert s["warrantiesExpiring"]["days30"] == 1
    assert s["warrantiesExpiring"]["items"][0]["name"] == "Router"


def test_summary_maintenance_overdue(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Furnace"}).get_json()
    past = (datetime.utcnow() - timedelta(days=3)).isoformat()
    auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "scheduledDate": past},
    )
    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["maintenance"]["overdue"] == 1
    assert s["maintenance"]["entries"][0]["overdue"] is True


def test_calendar_events(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "TV"}).get_json()
    exp = (datetime.utcnow() + timedelta(days=40)).isoformat()
    auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "TV", "warrantyExpires": exp},
    )
    events = auth_client.get("/api/v1/ha/calendar").get_json()
    assert any(e["category"] == "warranty" and "TV" in e["summary"] for e in events)
    # each event has start/end for an all-day calendar entry
    assert all("start" in e and "end" in e for e in events)


def test_ha_requires_auth(client):
    assert client.get("/api/v1/ha/summary").status_code == 401
