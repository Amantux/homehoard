"""add jobs (background task queue for async AI tooling)

Idempotent create: the 0001 metadata baseline builds this table on fresh/adopted
DBs, so this delta only adds it to DBs stamped before the model existed.

Revision ID: 0007_add_jobs
Revises: 0006_add_chat
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_add_jobs"
down_revision = "0006_add_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "jobs" in insp.get_table_names():
        return
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("group_id", sa.String(36), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_group_id", "jobs", ["group_id"])
    # At most one active (pending|running) job per group+kind.
    active = "status IN ('pending','running')"
    op.create_index("uq_jobs_active_per_group_kind", "jobs", ["group_id", "kind"],
                    unique=True, sqlite_where=sa.text(active),
                    postgresql_where=sa.text(active))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "jobs" in insp.get_table_names():
        op.drop_table("jobs")
