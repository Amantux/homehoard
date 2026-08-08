"""CSV-imported items must get a holding, and keep fractional quantity.

import_items never called ensure_holding, so an imported item had
placementCount 0: it didn't appear on its location page (listed via
loc.holdings) and the next holdings-touching action zeroed its quantity
(resync_item summed zero holdings). And _int_or truncated 2.5 -> 2 though
quantity is Float for exactly this.
"""
import io

from app.services import csv_io


def _import(auth_client, csv_text):
    return auth_client.post(
        "/api/v1/items/import",
        data={"csv": (io.BytesIO(csv_text.encode()), "items.csv")},
        content_type="multipart/form-data",
    )


def test_imported_item_gets_a_holding_and_appears_in_its_location(auth_client, app):
    csv_text = "HB.name,HB.quantity,HB.location\nHammer,3,Garage\n"
    r = _import(auth_client, csv_text)
    assert r.status_code in (200, 201)

    items = auth_client.get("/api/v1/items").get_json()["items"]
    hammer = [i for i in items if i["name"] == "Hammer"][0]
    assert hammer["placementCount"] == 1, "imported item has no holding"

    # It shows up where it lives (locations list via holdings).
    locs = auth_client.get("/api/v1/locations").get_json()
    garage = [x for x in locs if x["name"] == "Garage"][0]
    assert garage.get("itemCount", 0) >= 1


def test_imported_quantity_survives_a_later_holdings_action(auth_client, app):
    _import(auth_client, "HB.name,HB.quantity,HB.location\nDrill,4,Shed\n")
    items = auth_client.get("/api/v1/items").get_json()["items"]
    drill = [i for i in items if i["name"] == "Drill"][0]
    # a no-op-ish PUT must not zero the quantity via resync
    auth_client.put(f"/api/v1/items/{drill['id']}", json={"notes": "x"})
    after = auth_client.get(f"/api/v1/items/{drill['id']}").get_json()
    assert after["quantity"] == 4, "imported quantity was wiped"


def test_fractional_import_quantity_is_preserved():
    assert csv_io._num_or("2.5", 1) == 2.5
    assert csv_io._num_or("abc", 1) == 1
    assert csv_io._num_or("3", 1) == 3
