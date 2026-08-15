"""Policy-driven restock suggestions — which consumables are running low.

Mirrors Edibl's reorder service (the reference implementation, per the SOP's
reference-then-mirror rule), simplified to HomeHoard's model: no reservations,
no lot kinds — an item's quantity is already the sum of its holdings.

One source of truth for "is this low", shared by GET /restock, the HA summary
(so an automation or to-do card can act on it) and the notifier digest. An item
with no min_quantity has no policy and is never suggested: most inventory is
not a consumable, and nagging about a couch would teach people to ignore the
list.
"""
from ..extensions import db
from ..models import Item
from . import vault


def restock_state(item) -> dict | None:
    """The one low-stock computation. None when the item has no policy."""
    if item.min_quantity is None:
        return None
    on_hand = item.quantity or 0
    threshold = item.min_quantity
    target = item.target_quantity if item.target_quantity is not None else threshold
    # Enough to reach the target, but never a nonsensical zero/negative ask.
    need = round(max(target - on_hand, threshold - on_hand, 1), 4)
    return {
        "id": item.id,
        "name": item.name,
        "onHand": on_hand,
        "threshold": threshold,
        "target": target,
        "suggestedQuantity": need,
        "isLow": on_hand <= threshold,
    }


def restock_suggestions(gid, *, include_hidden=None) -> list[dict]:
    """Everything at/below its threshold, lowest first.

    Vault-aware via the standard query filter: an unlocked session sees its
    hidden consumables' needs, a locked one does not. The notifier digest must
    NOT pass include_hidden — it uses `never_hidden` semantics by calling this
    with the default in a request-less context, where visible() excludes.
    """
    q = vault.visible(
        db.session.query(Item).filter(
            Item.group_id == gid,
            Item.min_quantity.isnot(None),
            Item.archived.is_(False),
        ),
        include_hidden=include_hidden,
    )
    out = []
    for item in q.all():
        st = restock_state(item)
        if st is None or not st["isLow"]:
            continue
        st.pop("isLow")
        out.append(st)
    out.sort(key=lambda s: (s["onHand"], s["name"].lower()))
    return out
