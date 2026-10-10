"""Group scoping for /api/v1 loaders — the one place the tenant check lives.

A row in another group is reported as 404, never 403: a foreign id must be
indistinguishable from an absent one, so ids can't be probed across households.
"""
from flask import abort

from ..auth import current_group
from ..extensions import db

__all__ = ["get_owned_or_404"]


def get_owned_or_404(model, id_):
    """Load ``model`` by primary key, 404 if absent or owned by another group."""
    obj = db.session.get(model, id_)
    if obj is None or obj.group_id != current_group().id:
        abort(404)
    return obj

