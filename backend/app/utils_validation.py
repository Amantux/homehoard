"""Tiny shared coercions for request data (HomeHoard's counterpart to the
sibling apps' utils.py — created when the consumables policy needed a
float-or-null that refuses NaN/negatives instead of storing them)."""
from decimal import Decimal, InvalidOperation

# Quantity columns are Numeric(12, 3): at most 3 decimal places and 9 integer
# digits. Anything outside that would be silently rounded (Postgres) or stored
# with float drift (SQLite), so the API refuses it instead.
QTY_MAX = Decimal("999999999.999")


def to_quantity(value):
    """Parse a quantity into an exact Decimal, or None if it isn't one we can
    store: non-numeric, NaN/Infinity, more than 3 decimal places, or > QTY_MAX.
    Sign is NOT checked here (callers differ on whether 0 is allowed).
    Goes via str() so a JSON float 0.1 becomes Decimal("0.1"), not the binary
    expansion 0.1000000000000000055511151231257827."""
    if value is None or isinstance(value, bool):
        return None
    try:
        q = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not q.is_finite() or abs(q) > QTY_MAX or q.normalize().as_tuple().exponent < -3:
        return None
    return q


def positive_or_none(value):
    """A finite Decimal >= 0 (see to_quantity), else None. None also for junk —
    a policy field set to garbage should mean "not tracked", not a 500 or a NaN
    threshold."""
    q = to_quantity(value)
    if q is None or q < 0:
        return None
    return q
