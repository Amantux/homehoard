"""Bin.locationId and Label.parentId must be group-scoped (IDOR).

create/update_bin and create/update_label assigned the raw id with no
ownership check — group B could parent its bin under group A's location (and
leak A's location NAME via bin_summary) or nest its label under A's label
(cross-tenant read + state pollution both directions), and dangling FKs from
nonexistent ids.
"""


def _tok(client, email):
    client.post("/api/v1/users/register",
                json={"email": email, "password": "pw123456", "name": "X"})
    return client.post("/api/v1/users/login",
                       json={"username": email, "password": "pw123456"}
                       ).get_json()["token"]


def test_a_bin_cannot_reference_another_groups_location(client):
    a, b = _tok(client, "ba@x.com"), _tok(client, "bb@x.com")
    loc = client.post("/api/v1/locations", json={"name": "SecretRoom"},
                      headers={"Authorization": a}).get_json()

    r = client.post("/api/v1/bins",
                    json={"name": "B", "locationId": loc["id"]},
                    headers={"Authorization": b})
    assert r.status_code == 404
    # and the response never leaked A's location name
    assert "SecretRoom" not in r.get_data(as_text=True)


def test_a_label_cannot_parent_under_another_groups_label(client):
    a, b = _tok(client, "la@x.com"), _tok(client, "lb@x.com")
    parent = client.post("/api/v1/labels", json={"name": "SecretParent"},
                         headers={"Authorization": a}).get_json()

    r = client.post("/api/v1/labels",
                    json={"name": "Child", "parentId": parent["id"]},
                    headers={"Authorization": b})
    assert r.status_code == 404
    # A's label must not have gained a cross-group child
    a_labels = client.get("/api/v1/labels", headers={"Authorization": a}).get_json()
    a_parent = [x for x in a_labels if x["id"] == parent["id"]][0]
    assert not a_parent.get("children")


def test_a_nonexistent_location_on_a_bin_is_refused(client):
    a = _tok(client, "bn@x.com")
    r = client.post("/api/v1/bins", json={"name": "B", "locationId": "no-such-id"},
                    headers={"Authorization": a})
    assert r.status_code == 404


def test_a_bin_can_still_use_its_own_location(client):
    a = _tok(client, "bo@x.com")
    loc = client.post("/api/v1/locations", json={"name": "Mine"},
                      headers={"Authorization": a}).get_json()
    r = client.post("/api/v1/bins", json={"name": "B", "locationId": loc["id"]},
                    headers={"Authorization": a})
    assert r.status_code in (200, 201)
