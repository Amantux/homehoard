"""The shared report/digest row contract — the one module that owns row shapes.

One module, one row shape, for every report and digest in the house: the
inventory report, the alert digest, the Home Assistant summary's "needs
attention" rows, and whatever comes next. A report never hand-rolls its own row:
it builds a shared :class:`ReportRow`, validates it, and serializes it through
here.

``ReportRow`` is the shared core row and carries only non-report-specific core
keys — ``id``, ``title``, ``group_id`` (scope), ``timestamp``, ``summary``, ``status`` —
plus the shared ``action_url`` (where the operator acts). No per-report-specific key
may appear on the row.

Anything a specific report wants to say beyond the core keys is not a row field: it
rides in the quirks bag, carried alongside the row (not inside it) and threaded
verbatim through serialize/deserialize to that report's renderer. The registry
itself stays ignorant of which report a row belongs to.

* ``CORE_ROW_KEYS`` — the only keys a :class:`ReportRow` may carry.
* ``validate_report_row`` — integrity gate: a row must carry the shared core
  shape (required core keys present, types correct, no unknown keys) and must
  resolve to a real item before it is rendered or sent.
* ``serialize_report_row`` — the JSON-ready dict both sides agree on, carrying
  the optional ``quirks`` bag alongside the core keys verbatim (absent → None).
* ``build_item_row`` / ``build_checkout_overdue_row`` / ``build_warranty_soon_row`` /
  ``build_maintenance_overdue_row`` — the registry's row builders.
* ``serialize_item_row`` / ``serialize_checkout_overdue_row`` / ``serialize_warranty_soon_row`` /
  ``serialize_maintenance_overdue_row`` — per-report adapters mapping a core row
  onto that report's own wire keys (the renderer seam).
* ``ReportEntry`` / ``REPORTS`` — the registry's own entries: one per report/digest,
  carrying ``id``, ``title``, ``row_builder`` and an optional ``quirks`` bag of its own
  (``None`` when the report has none). The registry knows nothing about what a given
  report's quirks mean — each entry declares its own.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Mapping, TypeAlias

from ..models import Item, MaintenanceEntry
from ..timeutil import as_utc, utcnow

# Warranties within this window of the expiry date are "expiring" for report
# purposes. (The alert digest applies its own shorter window — services/alerts.)
_EXPIRING_SOON_DAYS = 60

_STATUS_LABELS = {
    "lifetime": "Lifetime",
    "active": "Active",
    "expiring": "Expiring soon",
    "expired": "Expired",
    "none": "—",
    "overdue": "Overdue",
}

# Plain-language tone for a status: 'ok' healthy, 'warn' watch, 'bad' past due.
# Derived here so every report surface renders one tone from the row's status.
_STATUS_TONES = {
    "lifetime": "ok",
    "active": "ok",
    "expiring": "warn",
    "expired": "bad",
    "none": "ok",
    "overdue": "bad",
}


CORE_ROW_KEYS: tuple[str, ...] = (
    "id",
    "title",
    "group_id",
    "timestamp",
    "summary",
    "status",
    "action_url",
)

# The wire shape of a row: the core keys plus the optional ``quirks`` bag carried
# alongside (never inside) the row. The bag is part of the wire shape, not of the
# core shape, and is deliberately not key-validated here — that is the owning
# report's own later per-report test.
ROW_WIRE_KEYS: tuple[str, ...] = CORE_ROW_KEYS + ("quirks",)

# The core keys a row must carry to be a valid report row: an ``id`` to resolve
# against, a ``title`` to put on the row, and a ``status`` to label and tone it.
REQUIRED_ROW_KEYS: tuple[str, ...] = ("id", "title", "status")

# The type contract of each core key — the shared core shape's own shape check.
CORE_KEY_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "title": (str,),
    "group_id": (str, type(None)),
    "timestamp": (str,),
    "summary": (str,),
    "status": (str,),
    "action_url": (str,),
}


# The optional quirks bag carried alongside a :class:`ReportRow`. Typed as a
# free-form JSON object that is explicitly NON-CONTRACT: the key names and value
# shapes are owned by the specific report's renderer, and nothing here validates
# them — the bag is copied verbatim through serialize/deserialize. A report that
# has no extras simply carries none (``None``).
QuirksDescriptor: TypeAlias = dict[str, Any] | None
"""Optional quirks bag for a report row — free-form, explicitly non-contract."""


@dataclass
class ReportRow:
    """The shared core row — the only keys a report/digest row may carry.

    Core keys only; no per-report-specific key may appear here. ``action_url`` is
    the shared "where the operator acts" surface the row carries.

    ``status`` is the row's own status key (``lifetime`` / ``active`` / ``expiring`` /
    ``expired`` / ``none`` for a warranty; ``overdue`` for a lend or maintenance), so a
    consumer renders its label and tone from the field rather than re-deriving
    presentation per surface.
    """

    id: str
    title: str
    group_id: str | None = None
    timestamp: str = ""
    summary: str = ""
    status: str = ""
    action_url: str = ""

    @property
    def status_label(self) -> str:
        """Plain-language label for the row's status — derived, not stored."""
        return _STATUS_LABELS.get(self.status, self.status)

    @property
    def status_tone(self) -> str:
        """Plain-language tone for the row's status — derived, not stored."""
        return _STATUS_TONES.get(self.status, "ok")


@dataclass(frozen=True)
class ReportEntry:
    """One registered report/digest — the registry's entry shape.

    An entry declares how its report/digest builds rows (``row_builder``) and
    whether it carries report-specific extras (``quirks`` — a free-form bag
    explicitly marked non-contract, or ``None`` when the report has none).

    The registry owns this shape and nothing more: it never imports or references a
    specific report's quirks, each entry declares its own, and the shared serializer
    copies the bag verbatim to that report's renderer.
    """

    id: str
    title: str
    row_builder: Callable[..., ReportRow]
    quirks: QuirksDescriptor = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("report entry requires a non-empty id")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError(f"report entry {self.id!r} requires a title")
        if self.row_builder is None:
            raise ValueError(f"report entry {self.id!r} requires a row builder")
        if self.quirks is not None and not isinstance(self.quirks, dict):
            raise ValueError(f"report entry {self.id!r} may declare only a quirks bag or None")

    def build(self, *args, **kwargs) -> ReportRow:
        """Build this entry's row from the source object(s) it owns."""
        return self.row_builder(*args, **kwargs)


def serialize_report_row(row: ReportRow, quirks: QuirksDescriptor = None) -> dict:
    """The JSON-ready dict for a row — the wire shape of the registry contract.

    The optional quirks bag rides alongside the core keys and is copied verbatim:
    no field-by-field validation, no key shaping — the owning report's renderer
    owns whatever keys the bag carries. Absent (``None``) when the row has no
    report-specific extras.
    """
    out = {
        "id": row.id,
        "title": row.title,
        "group_id": row.group_id or "",
        "timestamp": row.timestamp,
        "summary": row.summary,
        "status": row.status,
        "action_url": row.action_url,
    }
    out["quirks"] = quirks
    return out


def _is_present(value: Any) -> bool:
    """A required core key counts as present only when it carries a real string."""
    return isinstance(value, str) and bool(value.strip())


def _row_key_values(row: Any) -> dict[str, Any]:
    """The ``key -> value`` map a row carries before shape validation.

    A :class:`ReportRow` exposes its declared core fields through its instance
    mapping — which also picks up any report-specific key smuggled on afterwards —
    and a row-shaped mapping carries the same keys. Anything else is not a row.
    """
    if isinstance(row, ReportRow):
        return {str(k): v for k, v in dict(getattr(row, "__dict__", {}) or {}).items()}
    if isinstance(row, Mapping):
        return {str(k): v for k, v in dict(row).items()}
    raise ValueError("report rows must be ReportRow instances or row key maps")


def _validate_core_row(row: Any) -> dict[str, Any]:
    """The shared health/integrity core-shape gate.

    A row must carry the shared core shape only: the required core keys present,
    the core keys' types correct, and no key outside the core shape — a
    report-specific key on the row is a smuggling bug, not a row field, and is
    rejected here rather than shipped to a renderer.

    Per-report quirks are carried alongside the row (never inside it) and are
    deliberately not validated here; that is the owning report's own later test.

    Raises ``ValueError`` when the row does not carry the core shape.
    """
    values = _row_key_values(row)
    allowed = set(ROW_WIRE_KEYS) if isinstance(row, Mapping) else set(CORE_ROW_KEYS)
    unknown = sorted(k for k in values if k not in allowed)
    if unknown:
        raise ValueError(f"report row carries non-core fields: {', '.join(unknown)}")
    for key, expected in CORE_KEY_TYPES.items():
        if key not in values or values[key] is None:
            continue
        if not isinstance(values[key], expected):
            expected_types = "/".join(t.__name__ for t in expected)
            raise ValueError(
                f"report row field {key!r} has the wrong type: expected "
                f"{expected_types}, got {type(values[key]).__name__}"
            )
    missing = [k for k in REQUIRED_ROW_KEYS if not _is_present(values.get(k))]
    if missing:
        raise ValueError(f"report row missing required core keys: {', '.join(missing)}")
    return values


def validate_report_row(
    row: ReportRow,
    resolver: Callable[[str], Any] = None,
    *,
    group_id: str | None = None,
    db: Any = None,
) -> ReportRow:
    """Validate a report row — core shape, then that it resolves to a real item.

    The shared integrity gate first runs the core-shape check (required core keys
    present, types correct, no unknown keys — a row carrying report-specific
    fields is rejected), then resolves the row's item_ref.

    ``resolver`` lets a caller that already holds the queried rows supply its own
    lookup; without one the row is checked within the household via ``group_id`` +
    ``db`` (the same standard session lookups every service uses).

    Raises ``ValueError`` when the row does not carry the core shape or when the
    item_ref does not resolve — a report that points at a deleted or unknown item
    is a bug, not a row to render.
    """
    values = _validate_core_row(row)
    ref = str(values.get("id") or "")
    if resolver is not None:
        resolved = resolver(ref)
    else:
        resolved = _lookup(ref, group_id=group_id, db=db)
    if resolved is None:
        raise ValueError(
            f"report row item_ref does not resolve to a real item: {ref!r}"
        )
    return row


def _lookup(item_ref: str, *, group_id: str | None = None, db: Any = None):
    """Resolve an item_ref ('item:<id>' / 'maintenance:<id>') within a group."""
    kind, _, rid = item_ref.partition(":")
    if kind == "item" and rid:
        q = db.session.query(Item).filter(Item.id == rid)
        if group_id is not None:
            q = q.filter(Item.group_id == group_id)
        return q.first()
    if kind == "maintenance" and rid:
        entry = db.session.get(MaintenanceEntry, rid)
        if entry is None:
            return None
        if group_id is not None and (
            entry.item is None or entry.item.group_id != group_id
        ):
            return None
        return entry
    return None


def warranty_status(item: Item, now) -> str:
    """One of: lifetime, active, expiring, expired, none — the row's status source."""
    if item.lifetime_warranty:
        return "lifetime"
    if not item.warranty_expires:
        return "none"
    if as_utc(item.warranty_expires) < now:
        return "expired"
    if as_utc(item.warranty_expires) < now + timedelta(days=_EXPIRING_SOON_DAYS):
        return "expiring"
    return "active"


def build_item_row(item: Item, *, now=None, action_url: str = "") -> ReportRow:
    """Build the actionable report row for one inventory item.

    The registry is the only producer of rows: a surface hands over the item and
    gets a ReportRow back instead of hand-rolling its own row dict. The item_ref
    names the item the row is about (`item:<id>`), which is what the registry's
    validator resolves later.
    """
    now = as_utc(now) or utcnow()
    status = warranty_status(item, now)
    return ReportRow(
        id=f"item:{item.id}",
        title=item.name,
        group_id=item.group_id,
        timestamp=as_utc(item.warranty_expires).date().isoformat() if item.warranty_expires else "",
        summary=_status_reason(item, status),
        status=status,
        action_url=action_url,
    )


def serialize_item_row(
    row: ReportRow, item: Item, *, now, quirks: QuirksDescriptor = None
) -> dict:
    """Map a registry-built ReportRow back onto the inventory row keys.

    The inventory report's item-row shape (valuation + warranty fields) is owned
    here as well, so reports.py only calls into the registry and never builds the
    row dict itself. The ReportRow fields themselves ride along on the row, so
    report consumers render from the row contract rather than re-deriving a label
    or a link per surface. The optional ``quirks`` bag rides along verbatim (the
    inventory report's renderer owns its keys) and is handed to the frontend
    deserializer unchanged.
    """
    from ..schemas.serializers import iso, num  # local: schemas imports services

    from ..services import money

    out = {
        "id": item.id,
        "name": row.title,
        "location": item.location.name if item.location else "",
        "labels": [lbl.name for lbl in item.labels],
        "serialNumber": item.serial_number or "",
        "purchaseFrom": item.purchase_from or "",
        "purchaseDate": iso(item.purchase_date),
        "purchasePrice": money.out(item.purchase_price) or 0,
        "quantity": num(item.quantity) or 1,
        "lineValue": money.out(money.line_total(item.purchase_price, item.quantity)),
        "insured": bool(item.insured),
        "warrantyStatus": warranty_status(item, now),
        "imageId": next((a.document_id for a in item.attachments if a.primary), None),
    }
    # The ReportRow fields ride along on the inventory row as well: the SPA
    # renders report rows from these fields instead of re-deriving a label or a
    # link per surface. The inventory row's own id/name are the bare item fields;
    # the row's `id` is the kind-prefixed ref, so re-assert them after the merge.
    out.update(serialize_report_row(row, quirks=quirks))
    out["id"] = item.id
    out["name"] = row.title
    return out


def build_checkout_overdue_row(item: Item, *, action_url: str = "") -> ReportRow:
    """Overdue lend: the item went out and its due date has passed.

    The report registry is the only producer of rows, so the digest's
    ``overdueCheckouts`` kind gets its row here rather than in the alert service.
    The operator acts from the item's own page, which carries the check-out flow.
    """
    due = item.checkout_due.date().isoformat() if item.checkout_due else ""
    reason = f"Was due back before {due}."
    if item.checked_out_to:
        reason = f"{reason} (to {item.checked_out_to})"
    return ReportRow(
        id=f"item:{item.id}",
        title=item.name,
        group_id=item.group_id,
        timestamp=due,
        summary=reason,
        status="overdue",
        action_url=action_url,
    )


def build_warranty_soon_row(item: Item, *, action_url: str = "") -> ReportRow:
    """Warranty expiring within the alert window — still covered, lapsing soon."""
    expires = item.warranty_expires.date().isoformat() if item.warranty_expires else ""
    return ReportRow(
        id=f"item:{item.id}",
        title=item.name,
        group_id=item.group_id,
        timestamp=expires,
        summary=f"Warranty expires {expires}.",
        status="expiring",
        action_url=action_url,
    )


def build_maintenance_overdue_row(entry: MaintenanceEntry, *, action_url: str = "") -> ReportRow:
    """Overdue maintenance: scheduled before today, not yet completed."""
    scheduled = entry.scheduled_date.date().isoformat() if entry.scheduled_date else ""
    return ReportRow(
        id=f"maintenance:{entry.id}",
        title=entry.name,
        group_id=entry.item.group_id if entry.item else None,
        timestamp=scheduled,
        summary=f"Scheduled before {scheduled}.",
        status="overdue",
        action_url=action_url,
    )


# The report/digest registry — one entry per report/digest that produces rows.
# Each entry declares its own id, title, row builder and optional quirks bag
# (``None`` when the report has no extras); the registry itself stays ignorant of
# what a given report's quirks mean, and each report entry owns its own bag.
REPORTS: dict[str, ReportEntry] = {
    # The household inventory report: valuation + insurance summary.
    "inventory": ReportEntry(
        id="inventory",
        title="Inventory report",
        row_builder=build_item_row,
    ),
    # The alert digest's kinds: one entry per row kind the digest produces.
    "checkout_overdue": ReportEntry(
        id="checkout_overdue",
        title="Overdue checkouts",
        row_builder=build_checkout_overdue_row,
    ),
    "warranty_expiring_soon": ReportEntry(
        id="warranty_expiring_soon",
        title="Warranties expiring soon",
        row_builder=build_warranty_soon_row,
    ),
    "maintenance_overdue": ReportEntry(
        id="maintenance_overdue",
        title="Overdue maintenance",
        row_builder=build_maintenance_overdue_row,
    ),
}


def serialize_checkout_overdue_row(row: ReportRow, item: Item, *, quirks: QuirksDescriptor = None) -> dict:
    """Map an overdue-checkout row back onto the digest's per-entry keys.

    The optional ``quirks`` bag rides alongside the digest's per-entry keys and is
    handed to the digest's own renderer verbatim (absent → None). The registry hands
    the owning entry's bag over; the digest never shapes it here.
    """
    out = {"id": item.id, "name": row.title, "to": item.checked_out_to}
    out["quirks"] = quirks
    return out


def serialize_warranty_soon_row(row: ReportRow, item: Item, *, quirks: QuirksDescriptor = None) -> dict:
    """Map a warranty-soon row back onto the digest's per-entry keys.

    The optional ``quirks`` bag rides alongside the digest's per-entry keys and is
    handed to the digest's own renderer verbatim (absent → None).
    """
    out = {
        "id": item.id,
        "name": row.title,
        "expires": item.warranty_expires.date().isoformat() if item.warranty_expires else "",
    }
    out["quirks"] = quirks
    return out


def serialize_maintenance_overdue_row(row: ReportRow, entry: MaintenanceEntry, *, quirks: QuirksDescriptor = None) -> dict:
    """Map an overdue-maintenance row back onto the digest's per-entry keys.

    The optional ``quirks`` bag rides alongside the digest's per-entry keys and is
    handed to the digest's own renderer verbatim (absent → None).
    """
    out = {
        "id": entry.id,
        "name": row.title,
        "itemId": entry.item_id,
        "scheduled": entry.scheduled_date.date().isoformat() if entry.scheduled_date else "",
    }
    out["quirks"] = quirks
    return out


def _status_reason(item: Item, status: str) -> str:
    """A short, plain-language why-this-row-exists reason."""
    if status == "lifetime":
        return "Covered by the lifetime warranty."
    if status == "none":
        return "No warranty on file."
    expires = as_utc(item.warranty_expires).date().isoformat() if item.warranty_expires else ""
    if status == "expired":
        return f"Warranty expired {expires}."
    if status == "expiring":
        return f"Warranty expires {expires}."
    return f"Covered until {expires}."
