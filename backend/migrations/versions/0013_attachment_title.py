"""add attachments.title (display name for a link, which has no Document)

Uploads carry their name on the Document row. A LINK has no Document, so it had
nowhere to put one. Giving links a file-less Document purely to hold a title
would have made the "either a file or a link, never both" invariant incoherent.

Additive with a server_default, so existing rows are unchanged and create_all()
and a migrated database agree. Idempotent.

Revision ID: 0013_attachment_title
Revises: 0012_attachment_videos
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_attachment_title"
down_revision = "0012_attachment_videos"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def upgrade() -> None:
    if not _has_column("attachments", "title"):
        op.add_column(
            "attachments",
            sa.Column("title", sa.String(length=255), nullable=False,
                      server_default=""),
        )


def downgrade() -> None:
    if _has_column("attachments", "title"):
        op.drop_column("attachments", "title")
