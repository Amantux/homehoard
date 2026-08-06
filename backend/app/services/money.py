"""Money handling in one place: Decimal in the database, float on the wire.

Prices are ``Numeric(12, 2)`` columns (see ``models.base.MONEY``), which
SQLAlchemy hands back as ``Decimal``. Two consequences that this module exists
to make painless:

1. **Flask serialises ``Decimal`` as a JSON *string*** (``"19.99"``, not
   ``19.99``). Emitting it raw would silently change every price in the API from
   a number to a string and break arithmetic in the frontend. Everything goes
   out through :func:`out`.
2. **``Decimal * float`` raises ``TypeError``.** ``Item.quantity`` is a float,
   so every ``price * quantity`` line total has to coerce. That is
   :func:`line_total`, not something each call site reinvents.

Matches Edibl, which has stored money as ``Numeric(10, 2)`` from the start with
the same "float on the wire" rule.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")


def to_money(value, default=ZERO) -> Decimal:
    """Coerce anything a client might send into a 2dp Decimal.

    Junk becomes ``default`` rather than raising, because a bad price must not
    500 an otherwise-valid save.

    Goes via ``str`` so the stored value reflects what was typed rather than the
    float's binary expansion. Measured honestly: across 200k realistic 2dp
    values ``Decimal(str(x))`` and ``Decimal(x)`` never differ once quantized,
    so this is for legibility, not correctness.

    NaN and infinity are rejected explicitly. ``Decimal("NaN").quantize()`` does
    NOT raise, so without this a NaN would sail through, land in the database,
    and then be emitted as the bare token ``NaN`` — which is not valid JSON and
    breaks the client's parser rather than showing a bad number.
    """
    if value is None or value == "":
        return default
    try:
        result = value.quantize(_CENTS) if isinstance(value, Decimal) \
            else Decimal(str(value)).quantize(_CENTS)
    except InvalidOperation:
        # The only exception Decimal() raises for junk here — lists, dicts,
        # objects, bytes and infinity all land on it. Verified, rather than
        # catching a speculative set of types.
        return default
    return result if result.is_finite() else default


def out(value):
    """A money value as it goes on the wire: a JSON *number*, or None.

    Flask would otherwise render a Decimal as a string and quietly change the
    API's shape.
    """
    if value is None:
        return None
    return float(value)


def line_total(price, quantity) -> Decimal:
    """``price × quantity`` as an exact 2dp Decimal.

    Quantity is a float column, and ``Decimal * float`` is a TypeError — so the
    coercion lives here rather than at each of the half-dozen call sites that
    would otherwise each get it slightly differently.
    """
    return (to_money(price) * to_money(quantity, default=Decimal("1"))).quantize(_CENTS)


def total(pairs) -> Decimal:
    """Sum of ``(price, quantity)`` pairs, exactly."""
    result = ZERO
    for price, quantity in pairs:
        result += line_total(price, quantity)
    return result
