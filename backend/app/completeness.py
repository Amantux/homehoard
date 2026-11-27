"""Pure item-data completeness: required vs recommended fields, score + status.

The single source of truth for "how complete is this item". The item write path
validates against it and the data-completeness report will aggregate from it, so
the required/recommended rules live in one place and the two can never drift.

Deliberately framework-free: no Flask / SQLAlchemy / DB imports. ``completeness``
is pure — it reads the item record (a mapping or an attribute-bearing object) and
returns ``{"score": float, "status": "complete" | "partial" | "incomplete"}``.
"""

from datetime import date, datetime
from decimal import Decimal

COMPLETE = "complete"
PARTIAL = "partial"
INCOMPLETE = "incomplete"

# Per-item-type expected fields. ``required`` are the fields an item cannot be
# used / tracked without; ``recommended`` are the fields that add value or
# confidence but are not blockers.
ITEM_TYPES = {
    # An ordinary household item (the default inventory item).
    "physical": {
        "required": ("name",),
        "recommended": (
            "description",
            "notes",
            "serialNumber",
            "modelNumber",
            "manufacturer",
            "barcode",
            "purchasePrice",
            "purchaseFrom",
            "purchaseDate",
            "insured",
            "lifetimeWarranty",
            "warrantyExpires",
            "warrantyDetails",
        ),
    },
    # A consumable tracked against a restock policy: with no min quantity the item
    # cannot be tracked or suggested for re-ordering, so the policy is part of the
    # consumable's required profile.
    "consumable": {
        "required": ("name", "minQuantity"),
        "recommended": (
            "targetQuantity",
            "purchasePrice",
            "purchaseFrom",
            "purchaseDate",
            "description",
            "notes",
            "serialNumber",
            "modelNumber",
            "manufacturer",
            "barcode",
            "insured",
            "lifetimeWarranty",
            "warrantyExpires",
            "warrantyDetails",
        ),
    },
}

DEFAULT_ITEM_TYPE = "physical"


def _norm(key) -> str:
    """``purchasePrice`` / ``purchase_price`` / ``PurchasePrice`` -> ``purchaseprice``."""
    return str(key).strip().lower().replace("_", "")


def _snake(key: str) -> str:
    """camelCase -> snake_case (``minQuantity`` -> ``min_quantity``)."""
    out = []
    for ch in str(key):
        out.append("_" + ch.lower() if ch.isupper() else ch)
    return "".join(out).lstrip("_")


def _get(record, key):
    """Read ``key`` from a mapping or an attribute-bearing record. Tolerates the
    camelCase JSON names (``schemas.serializers.item_out``) and the snake_case
    model names, so the same field key works for both wire dicts and ORM rows."""
    n = _norm(key)
    if hasattr(record, "get"):
        for k, v in dict(record).items():
            if _norm(k) == n:
                return v
        return None
    for attr in {key, _snake(key), n}:
        v = getattr(record, attr, None)
        if v is not None:
            return v
    return None


def _is_filled(record, field) -> bool:
    """A field is filled when it holds a usable value (present, not None, not blank
    text). Booleans and numbers are real answers (``insured=False`` is known), dates
    are presence."""
    value = _get(record, field)
    if value is None:
        return False
    if isinstance(value, bool) or isinstance(
        value, (int, float, Decimal, datetime, date)
    ):
        return True
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _spec_for(item_type: str) -> dict:
    """The required/recommended field spec for one item type (defaulting safely)."""
    key = _norm(item_type) if item_type else ""
    return ITEM_TYPES.get(key, ITEM_TYPES[DEFAULT_ITEM_TYPE])


def item_type(record) -> str:
    """The item type a record belongs to (explicit type wins, else the default)."""
    t = _get(record, "type")
    if t is None:
        t = _get(record, "itemType")
    key = _norm(t) if t is not None else ""
    return key if key in ITEM_TYPES else DEFAULT_ITEM_TYPE


def required_fields(item_type: str) -> tuple:
    """The required fields for an item type (empty tuple for an unknown type)."""
    return tuple(_spec_for(item_type).get("required") or ())


def recommended_fields(item_type: str) -> tuple:
    """The recommended fields for an item type (empty tuple for an unknown type)."""
    return tuple(_spec_for(item_type).get("recommended") or ())


def completeness(item_record) -> dict:
    """Score one item record's data completeness.

    Returns ``{"score": float, "status": "complete"|"partial"|"incomplete"}`` where
    ``score`` is the fraction of the type's expected fields (required + recommended)
    that are filled — ``1.0`` complete, ``0.0`` incomplete — and ``status`` maps that
    to a coarse lifecycle state. Required fields are part of the expected set, so a
    missing required field always drags the score below the top.
    """
    spec = _spec_for(item_type(item_record))
    required = tuple(spec.get("required") or ())
    recommended = tuple(spec.get("recommended") or ())
    expected = list(required)
    for field in recommended:
        if _norm(field) not in {_norm(f) for f in expected}:
            expected.append(field)
    total = len(expected)
    score = (
        (sum(1 for f in expected if _is_filled(item_record, f)) / total)
        if total
        else 1.0
    )
    status = COMPLETE if score >= 1.0 else (INCOMPLETE if score <= 0.0 else PARTIAL)
    return {"score": float(score), "status": status}


def missing_fields(item_record) -> tuple:
    """The required fields of the record's item type that are not filled — the
    fields an item cannot be used / tracked without. Empty tuple when the record
    satisfies its type's required set. Recommended fields are never blockers (a
    partial item is *scored* partial by ``completeness``, not refused), so they
    are excluded here."""
    return tuple(
        f for f in required_fields(item_type(item_record)) if not _is_filled(item_record, f)
    )
