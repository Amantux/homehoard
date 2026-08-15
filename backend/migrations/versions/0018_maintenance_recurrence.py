"""maintenance_entries.recur_months — recurring maintenance

An entry with recur_months repeats every N calendar months: completing it
spawns the next scheduled entry (completed_date + N months, month-end
clamped) and the completed one stays as history. Nullable on purpose — NULL
means one-shot, which is what every existing entry is, so this is a pure
additive no-op on upgrade.

Idempotent (skips if present). The DOWNGRADE needs the FK dance: dropping a
column on SQLite REBUILDS the table, maintenance_entries is FK-referenced
(attachments.maintenance_entry_id) and this app enforces foreign keys — same
hazard 0015/0016 guard against.

Revision ID: 0018_maintenance_recurrence
Revises: 0017_chat_awaiting_vault
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_maintenance_recurrence"
down_revision = "0017_chat_awaiting_vault"
branch_labels = None
depends_on = None


def _columns(table) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "recur_months" not in _columns("maintenance_entries"):
        op.add_column(
            "maintenance_entries",
            sa.Column("recur_months", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if "recur_months" not in _columns("maintenance_entries"):
        return
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.get_context().autocommit_block():
            op.execute('DROP TABLE IF EXISTS "_alembic_tmp_maintenance_entries"')
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("maintenance_entries") as batch:
            batch.drop_column("recur_months")
    finally:
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
