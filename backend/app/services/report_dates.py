"""Household-local calendar dates: the "today" behind expiry checks and reports.

Item dates are calendar dates stored as UTC midnight (the UI's date input saves
``YYYY-MM-DD`` -> ``00:00``, see ``test_timezone.py``), so an "is this expiring
soon?" comparison is a calendar-date-vs-calendar-date check against the
household's *local* today — the day that rolls over at local midnight, never
UTC's. The instant comes from the shared timeutil (``utcnow`` -> ``as_utc`` ->
``to_local``, in the configured zone); the stored value is never shifted.
"""
from datetime import date, datetime, timedelta

from ..timeutil import as_utc, to_local, utcnow


def today_local(group, now=None) -> date:
    """The household's local calendar day — the ``today`` expiring checks and
    reports compare stored dates against. Scoped to ``group``'s household; the
    zone itself is the configured ``TZ``.

    ``now`` is injectable for testing, the same way consumers inject ``now``;
    it defaults to the shared :func:`utcnow`.
    """
    instant = as_utc(now) if now is not None else as_utc(utcnow())
    return to_local(instant).date()


def is_expiring(date, window_days: int, today) -> bool:
    """True when ``date`` is within ``window_days`` of ``today`` —
    ``today <= date <= today + timedelta(days=window_days)`` — both window edges
    inclusive. Accepts a ``date`` or ``datetime`` (stored dates are UTC-midnight
    datetimes; both are compared by calendar day) and returns a plain ``bool``.
    """
    day = date.date() if isinstance(date, datetime) else date
    ref = today.date() if isinstance(today, datetime) else today
    return ref <= day <= ref + timedelta(days=window_days)
