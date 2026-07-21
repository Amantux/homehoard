"""Keep an item's denormalized total quantity + primary placement in sync with
its holdings (the source of truth for per-placement quantities).

`ItemHolding` rows are authoritative. `Item.quantity` is their sum and
`Item.location_id`/`bin_id` mirror the *primary* (largest) holding — kept in sync
so every existing single-placement read (serializers, statistics, the location
tree, MCP, frontend) keeps working unchanged.
"""
from ..models import ItemHolding


def resync_item(item) -> None:
    """Recompute item.quantity (sum) + primary location/bin from its holdings.
    Call after any holding add/edit/move/delete."""
    holdings = list(item.holdings)
    if not holdings:
        item.quantity = 0
        return
    item.quantity = round(sum(h.quantity or 0 for h in holdings), 4)
    # Primary = the largest holding; tie-broken by id so it's deterministic.
    primary = min(holdings, key=lambda h: (-(h.quantity or 0), h.id or ""))
    item.location_id = primary.location_id
    item.bin_id = primary.bin_id


def ensure_holding(item) -> None:
    """Give an item its initial holding, mirroring its current placement, if it
    has none. Used on item create and by the migration backfill."""
    if item.holdings:
        return
    # Append to the relationship only (don't also set item_id / db.session.add,
    # which can double-insert into the collection). Cascade persists it.
    item.holdings.append(ItemHolding(
        location_id=item.location_id,
        bin_id=item.bin_id,
        quantity=item.quantity if item.quantity is not None else 1,
        group_id=item.group_id,
    ))


def primary_holding(item):
    """The holding whose bin/location the item currently mirrors (largest)."""
    if not item.holdings:
        return None
    return min(item.holdings, key=lambda h: (-(h.quantity or 0), h.id or ""))


def resync_bin_holdings(bin_) -> None:
    """A bin moved (its location changed) or is being detached: reflect it into
    every holding in the bin, then resync each affected item's primary/total."""
    affected = {h.item for h in bin_.holdings if h.item}
    for h in list(bin_.holdings):
        h.location_id = bin_.location_id
    for it in affected:
        resync_item(it)
