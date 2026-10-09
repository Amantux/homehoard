"""Field-level validation errors for the JSON API.

``abort_fields({"name": "Name is required"})`` produces a 422 whose body is
``{"error": <message>, "requestId": ..., "fields": {...}}`` (the ``unhandled``
handler in ``app/__init__.py`` adds ``fields``), so the SPA can render each
message under its input instead of a single toast.
"""
from typing import NoReturn

from flask import abort, request
from werkzeug.exceptions import UnprocessableEntity


class FieldValidationError(UnprocessableEntity):
    """422 carrying a ``fields`` mapping of field name -> curated message."""

    def __init__(self, fields: dict[str, str], message: str) -> None:
        super().__init__(description=message)
        self.fields = fields


def abort_fields(fields: dict[str, str], message: str = "validation failed") -> NoReturn:
    raise FieldValidationError(fields, message)


LIST_LIMIT_MAX = 1000


def list_limit() -> int:
    """The ``?limit=`` cap for a bare-array list route: 1..1000, default 1000.

    Clamped like items' ``pageSize`` so a list is never unbounded; a non-integer
    is a 400 (rather than items' silent fallback) because a caller asking for a
    cap they didn't get would otherwise not notice.
    """
    raw = request.args.get("limit")
    if raw is None or raw == "":
        return LIST_LIMIT_MAX
    try:
        n = int(raw)
    except ValueError:
        abort(400, description="limit must be an integer")
    return min(max(1, n), LIST_LIMIT_MAX)
