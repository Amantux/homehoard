"""add app_settings (instance-global key/value overrides, e.g. AI config)

Idempotent create: the 0001 metadata baseline builds this table on fresh/adopted
DBs, so this delta only adds it to DBs stamped before the model existed.

Revision ID: 0005_add_app_settings
Revises: 0004_uq_items_group_asset
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_add_app_settings"
down_revision = "0004_uq_items_group_asset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "app_settings" in insp.get_table_names():
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "app_settings" in insp.get_table_names():
        op.drop_table("app_settings")
