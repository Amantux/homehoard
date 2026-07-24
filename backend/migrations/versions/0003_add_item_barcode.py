"""add items.barcode (product UPC/EAN for scan-to-item)

Idempotent add-column + index: the metadata baseline (0001) create_all already
builds this on fresh/newly-adopted DBs, so this delta only adds it to DBs stamped
before the column existed. Dialect-safe (SQLite + Postgres).

Revision ID: 0003_add_item_barcode
Revises: 0002_add_item_search_text
Create Date: 2026-07-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_add_item_barcode"
down_revision = "0002_add_item_search_text"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def upgrade() -> None:
    if not _has_column("items", "barcode"):
        op.add_column("items", sa.Column("barcode", sa.String(64), nullable=True))
    insp = sa.inspect(op.get_bind())
    if "ix_items_barcode" not in {i["name"] for i in insp.get_indexes("items")}:
        op.create_index("ix_items_barcode", "items", ["barcode"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "ix_items_barcode" in {i["name"] for i in insp.get_indexes("items")}:
        op.drop_index("ix_items_barcode", table_name="items")
    if _has_column("items", "barcode"):
        op.drop_column("items", "barcode")
