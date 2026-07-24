"""baseline schema (metadata-driven)

The baseline is created from the app's model metadata rather than hand-written
table ops, so it stays in lockstep with the models and matches what the old
``db.create_all()`` produced. Fresh databases run this; existing pre-Alembic
installs are stamped to this revision instead (they already have the schema, and
startup brings any legacy schema up to baseline first). Future changes get their
own revisions on top.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-24
"""
import app.models  # noqa: F401 - registers every table on db.metadata
from alembic import op

from app.extensions import db

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    db.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    db.metadata.drop_all(bind=op.get_bind())
