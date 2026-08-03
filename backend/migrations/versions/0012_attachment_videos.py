"""attachments: url + maintenance_entry_id, and a nullable document_id

Lets an attachment be a LINK (url set, no Document on disk) as well as a file,
and lets it hang off a maintenance entry so a how-to video can belong to the
specific job it explains rather than the whole appliance.

Making ``document_id`` nullable is a widening — every existing row already has
one, so nothing is rewritten and no two-step deploy is needed. SQLite cannot
ALTER a column's nullability in place, so that part runs inside a batch
operation, which Alembic implements as a table rebuild; on Postgres it is a
plain ALTER. Idempotent add-columns so a partially-applied run can be retried.

Revision ID: 0012_attachment_videos
Revises: 0011_add_api_token_access
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_attachment_videos"
down_revision = "0011_add_api_token_access"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def _has_index(table, name) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return name in {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    if not _has_column("attachments", "url"):
        # server_default "" so existing rows read as "not a link" without a
        # backfill, and so create_all() and a migrated database agree.
        op.add_column(
            "attachments",
            sa.Column("url", sa.String(length=2048), nullable=False,
                      server_default=""),
        )
    if not _has_column("attachments", "maintenance_entry_id"):
        op.add_column(
            "attachments",
            sa.Column("maintenance_entry_id", sa.String(length=36), nullable=True),
        )
    if not _has_index("attachments", "ix_attachments_maintenance_entry_id"):
        # Indexed because every maintenance entry's payload filters on it.
        op.create_index(
            "ix_attachments_maintenance_entry_id", "attachments",
            ["maintenance_entry_id"],
        )

    # A link has no Document. SQLite needs a table rebuild for this; batch_alter
    # does that transparently and is a no-op ALTER on Postgres.
    with op.batch_alter_table("attachments") as batch:
        batch.alter_column("document_id", existing_type=sa.String(length=36),
                           nullable=True)


def downgrade() -> None:
    # Link-only rows have no Document and cannot be represented once
    # document_id is NOT NULL again, so drop them first. Deliberate and
    # explicit: silently leaving rows that violate the restored constraint
    # would fail the ALTER with a confusing error instead.
    op.execute("DELETE FROM attachments WHERE document_id IS NULL")

    # Everything in ONE batch. A bare DROP COLUMN of maintenance_entry_id fails
    # on SQLite ("unknown column ... in foreign key definition") because the
    # column is named by a foreign key: SQLite can only remove it by rebuilding
    # the table, which is exactly what batch_alter_table does. On Postgres these
    # are plain ALTERs. Verified by actually running the downgrade, which is how
    # this was found.
    with op.batch_alter_table("attachments") as batch:
        batch.alter_column("document_id", existing_type=sa.String(length=36),
                           nullable=False)
        if _has_index("attachments", "ix_attachments_maintenance_entry_id"):
            batch.drop_index("ix_attachments_maintenance_entry_id")
        if _has_column("attachments", "maintenance_entry_id"):
            batch.drop_column("maintenance_entry_id")
        if _has_column("attachments", "url"):
            batch.drop_column("url")
