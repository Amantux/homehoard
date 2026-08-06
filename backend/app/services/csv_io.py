"""CSV import/export compatible with homebox's column layout.

homebox uses a tab/comma separated export with a fixed set of ``HB.*`` columns.
This implements a pragmatic superset: standard headers plus ``HB.field.*`` for
custom fields and ``HB.label`` (semicolon separated).
"""
import csv
import io
from datetime import datetime

from ..extensions import db
from ..models import Item, Label, Location, ItemField
from . import money

HEADERS = [
    "HB.import_ref",
    "HB.location",
    "HB.labels",
    "HB.quantity",
    "HB.name",
    "HB.description",
    "HB.insured",
    "HB.serial_number",
    "HB.model_number",
    "HB.manufacturer",
    "HB.barcode",
    "HB.notes",
    "HB.purchase_from",
    "HB.purchase_price",
    "HB.purchase_time",
    "HB.lifetime_warranty",
    "HB.warranty_expires",
    "HB.warranty_details",
    "HB.sold_to",
    "HB.sold_price",
    "HB.sold_time",
    "HB.sold_notes",
]


def _dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Neutralize spreadsheet formula injection (CWE-1236): a cell starting with
    = + - @ (or a control char) is prefixed with a single quote so Excel/Sheets
    treats it as text, not a formula."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _FORMULA_LEAD:
        return "'" + s
    return s


def _csv_unescape(value):
    """Reverse _csv_safe on import so an export→import round-trip is lossless: strip
    the single leading quote we added before a formula-trigger char. Without this,
    ``-40C Probe`` re-imports as ``'-40C Probe`` and a negative number like
    ``-5.00`` re-imports as ``'-5.00`` (which then crashes float()/int()). A value
    a user literally typed as ``'=…`` is indistinguishable from our escaping — an
    accepted, rare ambiguity inherent to CSV-injection escaping."""
    if value and len(value) >= 2 and value[0] == "'" and value[1] in _FORMULA_LEAD:
        return value[1:]
    return value


def export_items(group_id) -> str:
    items = db.session.query(Item).filter_by(group_id=group_id).all()
    field_names = sorted(
        {f.name for i in items for f in i.fields}
    )
    headers = HEADERS + [f"HB.field.{n}" for n in field_names]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for i in items:
        row = [
            i.import_ref,
            i.location.name if i.location else "",
            ";".join(lbl.name for lbl in i.labels),
            i.quantity,
            i.name,
            i.description,
            i.insured,
            i.serial_number,
            i.model_number,
            i.manufacturer,
            i.barcode,
            i.notes,
            i.purchase_from,
            i.purchase_price,
            i.purchase_date.date().isoformat() if i.purchase_date else "",
            i.lifetime_warranty,
            i.warranty_expires.date().isoformat() if i.warranty_expires else "",
            i.warranty_details,
            i.sold_to,
            i.sold_price,
            i.sold_date.date().isoformat() if i.sold_date else "",
            i.sold_notes,
        ]
        field_map = {f.name: f.text_value for f in i.fields}
        row += [field_map.get(n, "") for n in field_names]
        writer.writerow([_csv_safe(v) for v in row])
    return out.getvalue()


def _get_or_create_location(group_id, name, cache):
    name = (name or "").strip()
    if not name:
        return None
    if name in cache:
        return cache[name]
    loc = (
        db.session.query(Location)
        .filter_by(group_id=group_id, name=name)
        .first()
    )
    if not loc:
        loc = Location(name=name, group_id=group_id)
        db.session.add(loc)
        db.session.flush()
    cache[name] = loc
    return loc


def _get_or_create_label(group_id, name, cache):
    name = name.strip()
    if not name:
        return None
    if name in cache:
        return cache[name]
    label = (
        db.session.query(Label).filter_by(group_id=group_id, name=name).first()
    )
    if not label:
        label = Label(name=name, group_id=group_id)
        db.session.add(label)
        db.session.flush()
    cache[name] = label
    return label


def import_items(group_id, text: str) -> int:
    # Detect delimiter (homebox historically used tab, newer uses comma).
    sample = text.split("\n", 1)[0]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    loc_cache, label_cache = {}, {}
    count = 0
    for raw_row in reader:
        # Reverse the export-side formula-injection escaping cell-by-cell so the
        # round-trip is lossless (and negatives don't crash numeric parsing).
        row = {k: _csv_unescape(v) for k, v in raw_row.items()}
        name = (row.get("HB.name") or "").strip()
        if not name:
            continue
        item = Item(
            group_id=group_id,
            import_ref=(row.get("HB.import_ref") or "").strip(),
            name=name,
            description=row.get("HB.description", ""),
            quantity=int(row.get("HB.quantity") or 1),
            insured=_bool(row.get("HB.insured")),
            serial_number=row.get("HB.serial_number", ""),
            model_number=row.get("HB.model_number", ""),
            manufacturer=row.get("HB.manufacturer", ""),
            barcode=(row.get("HB.barcode") or "").strip()[:64],
            notes=row.get("HB.notes", ""),
            purchase_from=row.get("HB.purchase_from", ""),
            purchase_price=money.to_money(row.get("HB.purchase_price")),
            purchase_date=_dt(row.get("HB.purchase_time")),
            lifetime_warranty=_bool(row.get("HB.lifetime_warranty")),
            warranty_expires=_dt(row.get("HB.warranty_expires")),
            warranty_details=row.get("HB.warranty_details", ""),
            sold_to=row.get("HB.sold_to", ""),
            sold_price=money.to_money(row.get("HB.sold_price")),
            sold_date=_dt(row.get("HB.sold_time")),
            sold_notes=row.get("HB.sold_notes", ""),
        )
        db.session.add(item)
        loc = _get_or_create_location(group_id, row.get("HB.location"), loc_cache)
        if loc:
            item.location = loc
        for lname in (row.get("HB.labels") or "").split(";"):
            label = _get_or_create_label(group_id, lname, label_cache)
            if label:
                item.labels.append(label)
        for key, value in row.items():
            if key and key.startswith("HB.field.") and value:
                item.fields.append(
                    ItemField(name=key[len("HB.field."):], text_value=value)
                )
        count += 1
    db.session.commit()
    return count
