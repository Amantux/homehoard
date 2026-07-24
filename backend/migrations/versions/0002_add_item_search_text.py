"""add items.search_text (AI web-search description for search)

Idempotent add-column: the metadata-driven baseline (0001) create_all already
builds this column on fresh and newly-adopted databases, so this delta only adds
it to databases that were stamped at 0001 BEFORE the column existed. Dialect-safe
(SQLite + Postgres).

Revision ID: 0002_add_item_search_text
Revises: 0001_baseline
Create Date: 2026-07-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_add_item_search_text"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def upgrade() -> None:
    if not _has_column("items", "search_text"):
        op.add_column("items", sa.Column("search_text", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("items", "search_text"):
        op.drop_column("items", "search_text")
