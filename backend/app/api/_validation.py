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


def json_body() -> dict:
    """The request's JSON body as a dict, or a 422. ``get_json(force=True)``
    hands back whatever parsed — a list, a string, a number — and the handler's
    ``data.get(...)`` then 500s; a non-object body is a client error."""
    # force=True as before: clients that omit the JSON content type keep working.
    data = request.get_json(force=True, silent=True)
    if data is None and not request.get_data():
        return {}  # empty body: same as the old ``... or {}``
    if not isinstance(data, dict):
        abort_fields({"body": "must be a JSON object"}, "Request body must be a JSON object")
    return data


# Emails the server mints for its own synthetic users: the shared local user
# (auth.DEFAULT_EMAIL) and HA-ingress users (``ha:<id>``). Registering or
# switching to one would collide with — or impersonate — those accounts.
_RESERVED_EMAIL_DOMAIN = "@easyinventory"
_RESERVED_EMAIL_PREFIX = "ha:"


def clean_email(value: object, field: str = "email") -> str:
    """Normalised (stripped, lower-cased) email, or a 422 on ``field``."""
    if not isinstance(value, str) or not value.strip():
        abort_fields({field: "Email is required"}, "Email is required")
    email = value.strip().lower()
    if email.startswith(_RESERVED_EMAIL_PREFIX) or email.endswith(_RESERVED_EMAIL_DOMAIN):
        abort_fields({field: "This email address is reserved"}, "This email address is reserved")
    local, at, domain = email.partition("@")
    if not at or not local or not domain or "@" in domain or any(c.isspace() for c in email):
        abort_fields({field: "Enter a valid email address"}, "Enter a valid email address")
    return email


def clean_name(value: object, field: str = "name") -> str:
    """A non-empty name string (stripped), or a 422 on ``field``."""
    if not isinstance(value, str) or not value.strip():
        abort_fields({field: "Name is required"}, "Name is required")
    return value.strip()


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
