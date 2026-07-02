"""Serialization helpers producing homebox-compatible camelCase JSON."""
from datetime import datetime, date


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, (datetime, date)):
        return dt.isoformat()
    return dt


def group_out(g):
    return {
        "id": g.id,
        "name": g.name,
        "currency": g.currency,
        "createdAt": iso(g.created_at),
        "updatedAt": iso(g.updated_at),
    }


def user_out(u):
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "isOwner": u.is_owner,
        "isSuperuser": u.is_superuser,
        "groupId": u.group_id,
        "groupName": u.group.name if u.group else None,
    }


def label_summary(l):
    return {
        "id": l.id,
        "name": l.name,
        "description": l.description,
        "color": l.color,
        "icon": l.icon,
        "parentId": l.parent_id,
        "createdAt": iso(l.created_at),
        "updatedAt": iso(l.updated_at),
    }


def label_out(l):
    data = label_summary(l)
    data["items"] = [item_summary(i) for i in l.items]
    data["children"] = [label_summary(c) for c in l.children]
    return data


def location_summary(loc):
    return {
        "id": loc.id,
        "name": loc.name,
        "description": loc.description,
        "createdAt": iso(loc.created_at),
        "updatedAt": iso(loc.updated_at),
    }


def location_out(loc, with_items=True):
    data = location_summary(loc)
    data["parent"] = location_summary(loc.parent) if loc.parent else None
    data["children"] = [location_summary(c) for c in loc.children]
    data["bins"] = [
        {"id": b.id, "name": b.name, "itemCount": len(b.items)} for b in loc.bins
    ]
    if with_items:
        data["items"] = [item_summary(i) for i in loc.items]
        data["totalPrice"] = sum((i.purchase_price or 0) * (i.quantity or 1)
                                 for i in loc.items)
    return data


def location_tree(loc):
    return {
        "id": loc.id,
        "name": loc.name,
        "type": "location",
        "children": [location_tree(c) for c in loc.children],
    }


def field_out(f):
    return {
        "id": f.id,
        "name": f.name,
        "type": f.type,
        "textValue": f.text_value,
        "numberValue": f.number_value,
        "booleanValue": f.boolean_value,
        "timeValue": iso(f.time_value),
    }


def document_out(d):
    return {"id": d.id, "title": d.title, "path": f"/api/v1/documents/{d.id}"}


def attachment_out(a):
    return {
        "id": a.id,
        "type": a.type,
        "primary": a.primary,
        "createdAt": iso(a.created_at),
        "updatedAt": iso(a.updated_at),
        "document": document_out(a.document) if a.document else None,
    }


def maintenance_out(m):
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "cost": m.cost,
        "scheduledDate": iso(m.scheduled_date),
        "completedDate": iso(m.completed_date),
        "itemId": m.item_id,
    }


def item_summary(i):
    primary = next((a for a in i.attachments if a.primary), None)
    return {
        "id": i.id,
        "name": i.name,
        "description": i.description,
        "quantity": i.quantity,
        "insured": i.insured,
        "archived": i.archived,
        "assetId": _fmt_asset(i.asset_id),
        "purchasePrice": i.purchase_price,
        "imageId": primary.document_id if primary else None,
        "location": location_summary(i.location) if i.location else None,
        "bin": bin_summary(i.bin) if i.bin else None,
        "labels": [label_summary(l) for l in i.labels],
        "createdAt": iso(i.created_at),
        "updatedAt": iso(i.updated_at),
    }


def item_out(i):
    data = item_summary(i)
    data.update(
        {
            "notes": i.notes,
            "serialNumber": i.serial_number,
            "modelNumber": i.model_number,
            "manufacturer": i.manufacturer,
            "purchaseFrom": i.purchase_from,
            "purchaseDate": iso(i.purchase_date),
            "syncChildLocations": i.sync_child_locations,
            "soldPrice": i.sold_price,
            "soldTo": i.sold_to,
            "soldDate": iso(i.sold_date),
            "soldNotes": i.sold_notes,
            "lifetimeWarranty": i.lifetime_warranty,
            "warrantyExpires": iso(i.warranty_expires),
            "warrantyDetails": i.warranty_details,
            "parent": item_summary(i.parent) if i.parent else None,
            "children": [item_summary(c) for c in i.children],
            "fields": [field_out(f) for f in i.fields],
            "attachments": [attachment_out(a) for a in i.attachments],
        }
    )
    return data


def notifier_out(n):
    return {
        "id": n.id,
        "name": n.name,
        "url": n.url,
        "isActive": n.is_active,
        "groupId": n.group_id,
        "userId": n.user_id,
        "createdAt": iso(n.created_at),
        "updatedAt": iso(n.updated_at),
    }


def bin_summary(b):
    primary = next((a for a in b.attachments if a.primary), None)
    return {
        "id": b.id,
        "name": b.name,
        "description": b.description,
        "locationId": b.location_id,
        "location": location_summary(b.location) if b.location else None,
        "imageId": primary.document_id if primary else None,
        "createdAt": iso(b.created_at),
        "updatedAt": iso(b.updated_at),
    }


def bin_out(b):
    data = bin_summary(b)
    data["items"] = [item_summary(i) for i in b.items]
    data["itemCount"] = len(b.items)
    data["totalPrice"] = sum((i.purchase_price or 0) * (i.quantity or 1)
                             for i in b.items)
    data["attachments"] = [attachment_out(a) for a in b.attachments]
    return data


def qrtag_out(t, scan_url=None):
    target = t.target
    if t.kind == "item":
        target_summary = item_summary(target) if target else None
    elif t.kind == "bin":
        target_summary = bin_summary(target) if target else None
    else:
        target_summary = location_summary(target) if target else None
    return {
        "id": t.id,
        "token": t.token,
        "description": t.description,
        "kind": t.kind,
        "source": getattr(t, "source", "generated"),
        "code": getattr(t, "code", "") or t.token,
        "codeFormat": getattr(t, "code_format", "qr"),
        "targetId": t.target_id,
        "target": target_summary,
        "scanUrl": scan_url,
        "createdAt": iso(t.created_at),
    }


def _fmt_asset(n: int) -> str:
    if not n:
        return "000-000"
    return f"{n // 1000:03d}-{n % 1000:03d}"
