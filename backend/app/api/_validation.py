"""Field-level validation errors for the JSON API.

``abort_fields({"name": "Name is required"})`` produces a 422 whose body is
``{"error": <message>, "requestId": ..., "fields": {...}}`` (the ``unhandled``
handler in ``app/__init__.py`` adds ``fields``), so the SPA can render each
message under its input instead of a single toast.
"""
from typing import NoReturn

from flask import request
from werkzeug.exceptions import UnprocessableEntity


class FieldValidationError(UnprocessableEntity):
    """422 carrying a ``fields`` mapping of field name -> curated message."""

    def __init__(self, fields: dict[str, str], message: str) -> None:
        super().__init__(description=message)
        self.fields = fields


def abort_fields(fields: dict[str, str], message: str = "validation failed") -> NoReturn:
    raise FieldValidationError(fields, message)


LIST_LIMIT_MAX = 1000


def list_limit() -> int | None:
    """Optional ``?limit=`` for a bare-array list route: None (unbounded, the
    original contract) unless the caller asks, then clamped to 1..1000 and a
    non-integer is ignored — the same rules as items' ``pageSize`` so one API
    has one way of reading a cap. A default cap was tried and rejected: a
    silently truncated locations list orphans children in the tree view.
    """
    raw = request.args.get("limit")
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return min(max(1, n), LIST_LIMIT_MAX)
