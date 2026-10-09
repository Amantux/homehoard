"""Field-level validation errors for the JSON API.

``abort_fields({"name": "Name is required"})`` produces a 422 whose body is
``{"error": <message>, "requestId": ..., "fields": {...}}`` (the ``unhandled``
handler in ``app/__init__.py`` adds ``fields``), so the SPA can render each
message under its input instead of a single toast.
"""
from typing import NoReturn

from werkzeug.exceptions import UnprocessableEntity


class FieldValidationError(UnprocessableEntity):
    """422 carrying a ``fields`` mapping of field name -> curated message."""

    def __init__(self, fields: dict[str, str], message: str) -> None:
        super().__init__(description=message)
        self.fields = fields


def abort_fields(fields: dict[str, str], message: str = "validation failed") -> NoReturn:
    raise FieldValidationError(fields, message)
