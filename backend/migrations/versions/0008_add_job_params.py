"""add jobs.params (per-run options: note, provider, model)

Idempotent add-column: the 0001 baseline builds the current table via create_all,
so this only patches DBs stamped between 0007 and now.

Revision ID: 0008_add_job_params
Revises: 0007_add_jobs
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_add_job_params"
down_revision = "0007_add_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "jobs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("jobs")}
    if "params" not in cols:
        op.add_column("jobs", sa.Column("params", sa.Text(), nullable=False,
                                        server_default=""))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "jobs" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("jobs")}
        if "params" in cols:
            op.drop_column("jobs", "params")
