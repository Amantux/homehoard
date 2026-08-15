"""Tiny shared coercions for request data (HomeHoard's counterpart to the
sibling apps' utils.py — created when the consumables policy needed a
float-or-null that refuses NaN/negatives instead of storing them)."""
import math


def positive_or_none(value):
    """A finite float >= 0, else None. None also for junk — a policy field set
    to garbage should mean "not tracked", not a 500 or a NaN threshold."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    return f
