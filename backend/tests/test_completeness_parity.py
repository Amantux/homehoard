"""Parity guard: the data-completeness report and the ?missing= item filter.

Two read surfaces answer the same question — which of the household's items are
missing a key fact — and they must answer it identically:

* the data-completeness report: ``backend/app/api/reports.py::inventory_report``
  derives each item's flags through ``backend/app/api/reports.py::_row`` and ships
  the per-field missing counts in ``summary.completeness``;
* the item list's gap filter: ``backend/app/api/items.py::list_items`` behind
  ``GET /api/v1/items?missing=<gap>`` (the SQL inverse of the reasons lives in
  ``backend/app/completeness.py::missing_clause``).

Both read the shared derivation in ``backend/app/completeness.py``, so the only
way they can still disagree is a regression in one of the call sites. This is the
parity guard: seed the shared fixture set, ask both surfaces, and fail naming
both call sites on any disagreement.
"""
from datetime import timedelta

from app.api.items import list_items
from app.api.reports import inventory_report
from app.completeness import COMPLETENESS_FIELDS, completeness_reasons
from app.extensions import db
from app.models import Attachment, Document, Item, Label, Location
from app.timeutil import utcnow

# The two call sites the parity test holds to the same answer.
REPORT_CALL_SITE = f"{inventory_report.__module__}.{inventory_report.__name__}"
LIST_CALL_SITE = f"{list_items.__module__}.{list_items.__name__}"


def _attach_photo(app, item) -> None:
    """A primary photo: file -> Document -> the one primary Attachment."""
    doc = Document(title=item.name, path=f"/tmp/{item.name}.png", group_id=item.group_id)
    db.session.add(doc)
    db.session.flush()
    db.session.add(Attachment(item=item, primary=True, type="photo", document_id=doc.id))


def _report_missing_ids(auth_client) -> dict:
    """gap -> the set of item ids the report flags as lacking that fact."""
    r = auth_client.get("/api/v1/reports/inventory").get_json()
    missing = {f: set() for f in COMPLETENESS_FIELDS}
    for row in r.get("items") or []:
        flags = row.get("completeness") or {}
        for f in COMPLETENESS_FIELDS:
            if not flags.get(f):
                missing[f].add(row["id"])
    return missing


def _filtered_missing_ids(auth_client, gap: str) -> set:
    """gap -> the set of item ids the list's ?missing=<gap> filter returns."""
    r = auth_client.get(f"/api/v1/items?missing={gap}").get_json()
    return {row["id"] for row in r.get("items") or []}


def test_completeness_parity_report_and_missing_filter_agree(app, auth_client, gid):
    """The report and the ?missing= filter must agree on the shared fixtures."""
    with app.app_context():
        loc = Location(name="Garage", group_id=gid)
        db.session.add(loc)
        db.session.flush()
        tools = Label(name="Tools", group_id=gid)
        db.session.add(tools)
        db.session.flush()

        # (a) complete — valued, photographed, placed, labelled, warranted, dated.
        complete = Item(name="Drill", group_id=gid, quantity=1, purchase_price=100,
                        location_id=loc.id, labels=[tools], lifetime_warranty=True,
                        purchase_date=utcnow())
        db.session.add(complete)
        _attach_photo(app, complete)

        # (b) missing-photo — valued, placed, labelled, warranted, dated, no photo.
        rake = Item(name="Rake", group_id=gid, quantity=2, purchase_price=25,
                    location_id=loc.id, labels=[tools], lifetime_warranty=True,
                    purchase_date=utcnow())
        db.session.add(rake)

        # (c) missing-date — everything but the purchase date.
        hammer = Item(name="Hammer", group_id=gid, quantity=2, purchase_price=25,
                      location_id=loc.id, labels=[tools], lifetime_warranty=True,
                      purchase_date=None)
        db.session.add(hammer)
        _attach_photo(app, hammer)

        # (d) stale — the warranty lapsed, the rest of the item is complete.
        saw = Item(name="Saw", group_id=gid, quantity=1, purchase_price=60,
                   location_id=loc.id, labels=[tools], lifetime_warranty=False,
                   warranty_expires=utcnow() - timedelta(days=30),
                   purchase_date=utcnow() - timedelta(days=200))
        db.session.add(saw)
        _attach_photo(app, saw)

        db.session.commit()

        expected_missing = {
            complete.id: set(),
            rake.id: {"photo"},
            hammer.id: {"purchaseDate"},
            saw.id: set(),
        }
        for item_id, want in expected_missing.items():
            got = completeness_reasons(db.session.get(Item, item_id))
            assert got == want, (
                f"completeness fixture mismatch for item {item_id}: "
                f"backend/app/completeness.py::completeness_reasons says {sorted(got)}, "
                f"expected {sorted(want)}"
            )

        report_missing = _report_missing_ids(auth_client)
        for gap in COMPLETENESS_FIELDS:
            listed = _filtered_missing_ids(auth_client, gap)
            flagged = report_missing.get(gap) or set()
            assert listed == flagged, (
                f"completeness parity failure: {REPORT_CALL_SITE} and {LIST_CALL_SITE} "
                f"disagree for gap {gap!r}: the report flags {sorted(flagged)} as "
                f"incomplete, the ?missing=<gap> list filter returned {sorted(listed)}"
            )
