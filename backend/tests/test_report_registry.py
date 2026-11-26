"""The shared ReportRow contract — one module, core keys only."""
import dataclasses
import json
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Item
from app.services import report_registry as rr
from app.timeutil import utcnow


def test_core_row_keys_are_the_shared_core_only():
    names = tuple(f.name for f in dataclasses.fields(rr.ReportRow))
    assert names == ("id", "title", "group_id", "timestamp", "summary", "status", "action_url")
    assert set(names) == set(rr.CORE_ROW_KEYS)
    # Nothing report-specific may ride on the shared row itself: no per-report
    # key (a lend's "to", a warranty's "expires", a maintenance's "scheduled", …).
    assert not (
        {"to", "expires", "itemId", "scheduled", "lineValue", "warrantyStatus", "item_ref"}
        & set(names)
    )


def test_build_item_row_carries_only_core_keys(app, auth_client, gid):
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    auth_client.put(
        f"/api/v1/items/{it['id']}",
        json={"name": "Drill", "warrantyExpires": (utcnow() + timedelta(days=400)).isoformat(),
              "insured": True, "purchasePrice": 100, "quantity": 1},
    )
    with app.app_context():
        item = db.session.get(Item, it["id"])
        row = rr.build_item_row(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
    assert row.id == f"item:{it['id']}"
    assert row.title == "Drill"
    assert row.group_id == gid
    assert row.timestamp
    assert row.summary
    assert row.status
    assert row.action_url == f"/#/items/{it['id']}"


def test_serialize_report_row_emits_the_core_keys_only():
    row = rr.ReportRow(id="item:7", title="Drill", timestamp="2026-01-01",
                       summary="Covered until 2026-06-01.", status="active",
                       action_url="/#/items/7")
    out = rr.serialize_report_row(row)
    # Core keys only, plus the optional quirks bag (absent → None).
    assert set(out) == set(rr.CORE_ROW_KEYS) | {"quirks"}
    assert out["id"] == "item:7"
    assert out["title"] == "Drill"
    assert out["action_url"] == "/#/items/7"
    assert out["quirks"] is None


def test_serialize_report_row_copies_the_quirks_bag_verbatim():
    row = rr.ReportRow(id="item:7", title="Drill", timestamp="2026-01-01",
                       summary="Covered until 2026-06-01.", status="active",
                       action_url="/#/items/7")
    quirks = {"to": "Mom", "note": {"private": True}, "nested": [1, 2, {"deep": None}]}
    out = rr.serialize_report_row(row, quirks=quirks)
    # No field-by-field validation / no key shaping: the bag rides untouched.
    assert out["quirks"] == quirks


def test_quirks_round_trip_preserves_the_bag_byte_for_byte():
    row = rr.ReportRow(id="item:7", title="Drill", status="active")
    quirks = {"to": "Mom", "anything": {"goes": [1, 2, 3]}}
    wire = json.loads(json.dumps(rr.serialize_report_row(row, quirks=quirks)))["quirks"]
    again = rr.serialize_report_row(row, quirks=wire)["quirks"]
    assert json.dumps(again, sort_keys=True) == json.dumps(quirks, sort_keys=True)


def test_serialize_item_row_hands_the_quirks_bag_to_the_renderer_seam(app, auth_client, gid):
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    with app.app_context():
        item = db.session.get(Item, it["id"])
        row = rr.build_item_row(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
        out = rr.serialize_item_row(
            rr.validate_report_row(row, group_id=gid, db=db), item, now=utcnow(),
            quirks={"to": "Mom"},
        )
    assert out["quirks"] == {"to": "Mom"}
    assert out["name"] == "Drill"


def test_validate_report_row_passes_a_real_item_and_rejects_a_stale_one(app, auth_client, gid):
    with app.app_context():
        db.session.add(Item(name="Mug", purchase_price=5, group_id=gid))
        db.session.commit()
        real = db.session.query(Item).filter_by(group_id=gid).first().id
        ok = rr.validate_report_row(
            rr.ReportRow(id=f"item:{real}", title="Mug", status="none"),
            group_id=gid, db=db,
        )
        assert ok.id == f"item:{real}"
        with pytest.raises(ValueError):
            rr.validate_report_row(
                rr.ReportRow(id="item:999999", title="Ghost", status="none"),
                group_id=gid, db=db,
            )


def test_validate_report_row_accepts_a_valid_core_row(app, auth_client, gid):
    """A well-formed core row passes the shape gate and resolves to a real item."""
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    with app.app_context():
        item = db.session.get(Item, it["id"])
        row = rr.build_item_row(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
        ok = rr.validate_report_row(row, group_id=gid, db=db)
    assert ok.id == f"item:{it['id']}"


def test_validate_report_row_rejects_a_row_with_report_specific_keys(app, auth_client, gid):
    """A report-specific key on the row is not core shape — the gate rejects it.

    The shared row may only carry the core keys; anything a specific report wants
    to say rides in the (non-contract) quirks bag carried alongside, never on the
    row itself.
    """
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    with app.app_context():
        item = db.session.get(Item, it["id"])
        row = rr.build_item_row(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
        row.to = "Mom"  # a lend-specific key smuggled onto the shared row
        with pytest.raises(ValueError):
            rr.validate_report_row(row, group_id=gid, db=db)


def test_validate_report_row_rejects_a_row_missing_required_core_keys(app, auth_client, gid):
    """A row without the required core keys does not carry the core shape."""
    with app.app_context():
        with pytest.raises(ValueError):
            rr.validate_report_row(
                rr.ReportRow(id="item:7", title="Drill"),
                group_id=gid, db=db,
            )


def test_registry_entries_validate_shape():
    # The registry entry shape: id, title, row builder, optional quirks descriptor.
    assert set(rr.REPORTS) == {
        "inventory", "checkout_overdue", "warranty_expiring_soon", "maintenance_overdue",
    }
    for entry in rr.REPORTS.values():
        assert entry.id and entry.title and entry.row_builder
        assert entry.quirks is None or isinstance(entry.quirks, dict)


def test_report_entry_requires_id_title_and_row_builder():
    with pytest.raises(ValueError):
        rr.ReportEntry(id="", title="No id", row_builder=rr.build_checkout_overdue_row)
    with pytest.raises(ValueError):
        rr.ReportEntry(id="no-title", title="", row_builder=rr.build_checkout_overdue_row)
    with pytest.raises(ValueError):
        rr.ReportEntry(id="no-builder", title="No builder", row_builder=None)
    with pytest.raises(ValueError):
        rr.ReportEntry(id="bad-quirks", title="Bad quirks",
                       row_builder=rr.build_checkout_overdue_row, quirks="not-a-bag")


def test_report_entry_carries_its_own_quirks_and_defaults_to_none():
    bare = rr.ReportEntry(id="bare", title="Bare", row_builder=rr.build_checkout_overdue_row)
    assert bare.quirks is None
    quirky = rr.ReportEntry(id="quirky", title="Quirky",
                             row_builder=rr.build_checkout_overdue_row, quirks={"to": "Mom"})
    assert quirky.quirks == {"to": "Mom"}


def test_report_with_no_quirks_entry_still_works(app, auth_client, gid):
    # A report that declares no quirks entry still builds, validates and serializes,
    # with the absent bag landing as None on the wire.
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    with app.app_context():
        item = db.session.get(Item, it["id"])
        entry = rr.REPORTS["inventory"]
        row = entry.build(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
        out = rr.serialize_item_row(
            rr.validate_report_row(row, group_id=gid, db=db), item, now=utcnow(),
            quirks=entry.quirks,
        )
    assert out["name"] == "Drill"
    assert out["quirks"] is None


def test_registry_entry_quirks_flow_to_the_row_verbatim(app, auth_client, gid):
    it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
    with app.app_context():
        item = db.session.get(Item, it["id"])
        entry = rr.ReportEntry(
            id="quirky-item", title="Quirky item",
            row_builder=rr.build_item_row, quirks={"to": "Mom", "note": {"private": True}},
        )
        row = entry.build(item, now=utcnow(), action_url=f"/#/items/{it['id']}")
        out = rr.serialize_item_row(
            rr.validate_report_row(row, group_id=gid, db=db), item, now=utcnow(),
            quirks=entry.quirks,
        )
    assert out["quirks"] == {"to": "Mom", "note": {"private": True}}


def test_sweep_all_report_entries_build_core_only_rows(app, auth_client, gid):
    """The no-smuggling sweep over every registered report/digest builder.

    No report adds fields to a ReportRow directly: each entry's row comes back
    from its own builder as a shared :class:`ReportRow` carrying only the core
    keys, and anything a specific report wants to say beyond the core shape rides
    in that entry's quirks bag — handed to the report's renderer verbatim by the
    serializer, never smuggled onto the row as a field.
    """
    from app.models import MaintenanceEntry

    with app.app_context():
        it = auth_client.post("/api/v1/items", json={"name": "Drill", "purchasePrice": 100}).get_json()
        item = db.session.get(Item, it["id"])
        maintenance = MaintenanceEntry(name="Oil change", item_id=item.id,
                                       scheduled_date=utcnow() - timedelta(days=5))
        db.session.add(maintenance)
        db.session.flush()

        built = {
            "inventory": lambda e: e.build(item, now=utcnow(), action_url=f"/#/items/{item.id}"),
            "checkout_overdue": lambda e: e.build(item, action_url=f"/#/items/{item.id}"),
            "warranty_expiring_soon": lambda e: e.build(item, action_url=f"/#/items/{item.id}"),
            "maintenance_overdue": lambda e: e.build(maintenance, action_url="/#/maintenance"),
        }

        for key, build in built.items():
            entry = rr.REPORTS[key]
            row = build(entry)
            assert isinstance(row, rr.ReportRow), f"{key}: the report built a non-ReportRow"
            carried = set(vars(row) or {})
            assert carried <= set(rr.CORE_ROW_KEYS), (
                f"{key}: report row carries non-core fields: "
                f"{sorted(carried - set(rr.CORE_ROW_KEYS))}"
            )
            # The entry's quirks bag rides to the owning report's renderer seam verbatim.
            if key == "inventory":
                wire = rr.serialize_item_row(
                    rr.validate_report_row(row, group_id=gid, db=db), item, now=utcnow(),
                    quirks=entry.quirks,
                )
            elif key == "checkout_overdue":
                wire = rr.serialize_checkout_overdue_row(
                    rr.validate_report_row(row, group_id=gid, db=db), item, quirks=entry.quirks,
                )
            elif key == "warranty_expiring_soon":
                wire = rr.serialize_warranty_soon_row(
                    rr.validate_report_row(row, group_id=gid, db=db), item, quirks=entry.quirks,
                )
            else:
                wire = rr.serialize_maintenance_overdue_row(
                    rr.validate_report_row(row, group_id=gid, db=db), maintenance, quirks=entry.quirks,
                )
            assert wire["quirks"] == entry.quirks, (
                f"{key}: the quirks bag was not handed to the renderer verbatim"
            )
