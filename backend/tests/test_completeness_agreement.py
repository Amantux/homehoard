"""Agreement between the item edit path and backend/app/completeness.py.

``backend/app/completeness.py`` is the single source of truth for an item's
required vs recommended fields and for the resulting score/status. The item write
path (``backend/app/api/items.py::_apply``) validates through it via
``missing_fields`` — the module is completeness under the hood — so the handlers
must not carry an inline copy of the rules, and the future data-completeness
report must call the module rather than re-implement the rules.

These tests are the contract that keeps the edit path and the future report in
sync: for the same item record, the module's answer is the one answer, and the
edit path must agree with it — accept what is complete, refuse what is
incomplete, score partials without refusing.
"""

from app.completeness import completeness, missing_fields


# A physical item with every required + recommended field filled in.
PHYSICAL_COMPLETE = {
    "name": "Drill",
    "description": "Cordless drill",
    "notes": "In the blue case",
    "serialNumber": "SN-1",
    "modelNumber": "M-2",
    "manufacturer": "Acme",
    "barcode": "0123456789012",
    "purchasePrice": "19.99",
    "purchaseFrom": "Hardware Co",
    "purchaseDate": "2024-05-01T00:00:00Z",
    "insured": True,
    "lifetimeWarranty": True,
    "warrantyExpires": "2030-01-01T00:00:00Z",
    "warrantyDetails": "Accidental damage",
}

# A physical item whose required name is blank -> nothing filled -> incomplete.
PHYSICAL_NEARLY_EMPTY = {"name": ""}

# A consumable whose required policy fields are blank/missing -> nothing filled.
CONSUMABLE_COMPLETE = {
    "type": "consumable",
    "name": "Drill",
    "minQuantity": 2,
    "targetQuantity": 4,
    "purchasePrice": "19.99",
    "purchaseFrom": "Hardware Co",
    "purchaseDate": "2024-05-01T00:00:00Z",
    "description": "Cordless drill",
    "notes": "Keep spare",
    "serialNumber": "SN-1",
    "modelNumber": "M-2",
    "manufacturer": "Acme",
    "barcode": "0123456789012",
    "insured": True,
    "lifetimeWarranty": True,
    "warrantyExpires": "2030-01-01T00:00:00Z",
    "warrantyDetails": "Accidental damage",
}

CONSUMABLE_NEARLY_EMPTY = {"type": "consumable", "name": "", "minQuantity": None}

COMPLETE = {"score": 1.0, "status": "complete"}
INCOMPLETE = {"score": 0.0, "status": "incomplete"}


# ---- backend/app/completeness.py, tested directly, per item type ----

def test_module_physical_fully_populated_is_complete():
    assert completeness(PHYSICAL_COMPLETE) == COMPLETE
    assert missing_fields(PHYSICAL_COMPLETE) == ()


def test_module_physical_nearly_empty_is_incomplete():
    assert completeness(PHYSICAL_NEARLY_EMPTY) == INCOMPLETE
    assert missing_fields(PHYSICAL_NEARLY_EMPTY) == ("name",)


def test_module_consumable_fully_populated_is_complete():
    assert completeness(CONSUMABLE_COMPLETE) == COMPLETE
    assert missing_fields(CONSUMABLE_COMPLETE) == ()


def test_module_consumable_nearly_empty_is_incomplete():
    assert completeness(CONSUMABLE_NEARLY_EMPTY) == INCOMPLETE
    assert missing_fields(CONSUMABLE_NEARLY_EMPTY) == ("name", "minQuantity")


# ---- the edit path must agree with the module on the same record ----

def _item(c, **kw):
    return c.post("/api/v1/items", json=kw)


def _get(c, item_id):
    return c.get(f"/api/v1/items/{item_id}").get_json()


def test_edit_path_agrees_with_module_on_fully_populated_item(auth_client):
    created = _item(auth_client, name="Drill").get_json()

    r = auth_client.put(f"/api/v1/items/{created['id']}", json=PHYSICAL_COMPLETE)
    assert r.status_code == 200, r.get_json()
    edited = r.get_json()

    # The item the edit path just returned is scored by the module itself, and
    # for the fully-populated fixture that must come out complete.
    assert completeness(edited) == completeness(PHYSICAL_COMPLETE) == COMPLETE


def test_edit_path_refuses_what_module_calls_incomplete(auth_client):
    created = _item(auth_client, name="Drill").get_json()

    # A nearly-empty record (blank required name) -> the module says incomplete.
    assert completeness({"name": "   "}) == INCOMPLETE

    r = auth_client.put(f"/api/v1/items/{created['id']}", json={"name": "   "})
    assert r.status_code == 422
    body = r.get_json()
    assert body["fields"] == {"name": "name is required"}
