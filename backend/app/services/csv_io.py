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
            ";".join(l.name for l in i.labels),
            i.quantity,
            i.name,
            i.description,
            i.insured,
            i.serial_number,
            i.model_number,
            i.manufacturer,
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
        writer.writerow(row)
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
    for row in reader:
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
            notes=row.get("HB.notes", ""),
            purchase_from=row.get("HB.purchase_from", ""),
            purchase_price=float(row.get("HB.purchase_price") or 0),
            purchase_date=_dt(row.get("HB.purchase_time")),
            lifetime_warranty=_bool(row.get("HB.lifetime_warranty")),
            warranty_expires=_dt(row.get("HB.warranty_expires")),
            warranty_details=row.get("HB.warranty_details", ""),
            sold_to=row.get("HB.sold_to", ""),
            sold_price=float(row.get("HB.sold_price") or 0),
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
