"""Data-completeness gaps: which key facts an item lacks, and how to filter
for them.

The inventory report and the item list both answer "which of my items are
missing <fact>?". This module owns that vocabulary — the ordered gap keys, the
per-item missing flags, and the SQL clause selecting the items lacking a gap — so
the report's per-field counts and the ``GET /items?missing=`` filter can never
drift apart.
"""
from ..extensions import db
from ..models import Attachment, Item, Label
from ..services import money

# The key facts the report treats as the shape of a complete item, in report
# order: value, photo, location, label, warranty date, purchase date.
COMPLETENESS_FIELDS = ("value", "photo", "location", "label", "warrantyDate", "purchaseDate")

# Canonical keys are camelCase (warrantyDate) but a ?missing= travels over HTTP
# where a client may send any casing — normalize through this lowercase index so
# the list filter and the report's key vocabulary cannot drift apart on spelling.
GAP_KEYS = {f.lower(): f for f in COMPLETENESS_FIELDS}


def normalize_gap(gap: str | None) -> str | None:
    """The canonical gap key for ``gap`` (case-insensitive), or None if unknown."""
    return GAP_KEYS.get((gap or "").strip().lower())


def completeness_flags(i) -> dict:
    """Which key facts this item lacks, as the per-item flags the report ships.

    A fact is missing when the item's line value is zero (nothing valued), it
    holds no primary photo, no placement, no label, no warranty date, or no
    purchase date — the same derivations the report row applied before.
    """
    return {
        "value": bool(money.out(money.line_total(i.purchase_price, i.quantity))),
        "photo": bool(next((a.document_id for a in (i.attachments or []) if a.primary), None)),
        "location": bool(i.location or i.bin),
        "label": bool(i.labels),
        "warrantyDate": bool(i.lifetime_warranty or i.warranty_expires),
        "purchaseDate": bool(i.purchase_date),
    }


def missing_clause(gap: str):
    """SQL WHERE clause for the items that LACK ``gap`` — the inverse of the
    per-item completeness flag. ``None`` for an unrecognized gap (no filtering).
    """
    if gap == "value":
        # Nothing valued: no purchase price or quantity on the line.
        return db.or_(Item.purchase_price.is_(None), Item.purchase_price <= 0,
                     Item.quantity.is_(None), Item.quantity <= 0)
    if gap == "photo":
        # No primary attachment (the item's photo) on file.
        return ~Item.attachments.any(Attachment.primary.is_(True))
    if gap == "location":
        # An item lives in a bin OR directly in a location; a bin implies one.
        return db.and_(Item.location_id.is_(None), Item.bin_id.is_(None))
    if gap == "label":
        # No label assigned.
        return ~Item.labels.any(Label.id.isnot(None))
    if gap == "warrantyDate":
        # No lifetime warranty and no expiry date on file.
        return db.and_(Item.lifetime_warranty.is_(False), Item.warranty_expires.is_(None))
    if gap == "purchaseDate":
        # Nothing bought-recorded on the item.
        return Item.purchase_date.is_(None)
    return None
