"""UTC time helpers — the one place the app decides what "now" and "a timestamp" mean.

Storage is naive UTC (plain ``DateTime`` columns; SQLAlchemy drops the tzinfo on
write and loads naive values). The API contract is ISO-8601 *with* an explicit
``+00:00`` offset, so clients never have to guess. Rules:

- produce "now" with :func:`utcnow` (aware UTC);
- compare a loaded column value against it through :func:`as_utc`
  (aware vs naive comparison raises ``TypeError``);
- emit timestamps with :func:`iso_utc`;
- render a calendar date for a human (CSV export, monthly buckets) through
  :func:`to_local`, which uses the configured ``TZ`` (the add-on picks up Home
  Assistant's zone at boot). Storage never changes zone.
"""
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, has_app_context


def utcnow() -> datetime:
    """The current instant as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalise to aware UTC: a naive value is taken to be UTC (how it is
    stored); an aware value is converted to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime | date | None) -> str | None:
    """ISO-8601 with an explicit ``+00:00`` offset. A bare ``date`` has no
    time-of-day to anchor an offset to, so it passes through as ``YYYY-MM-DD``."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        aware = as_utc(dt)
        assert aware is not None
        return aware.isoformat()
    return dt.isoformat()


def local_zone() -> tzinfo:
    """The configured display zone (settings ``TZ``). UTC outside an app
    context, or when the name is unknown — config validation already warned."""
    if not has_app_context():
        return timezone.utc
    name = (current_app.config["SETTINGS"].TZ or "").strip()
    if not name or name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def to_local(dt: datetime | None) -> datetime | None:
    """A stored (naive-UTC) or aware value as an aware datetime in :func:`local_zone`."""
    if dt is None:
        return None
    aware = as_utc(dt)
    assert aware is not None
    return aware.astimezone(local_zone())
