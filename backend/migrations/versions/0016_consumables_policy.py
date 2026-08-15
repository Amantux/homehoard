"""items.min_quantity + items.target_quantity — the consumables/restock policy

An item with a min_quantity is a tracked consumable: at or below it, the
restock list (GET /restock, the HA summary, and the notifier digest) suggests
buying enough to reach target_quantity, or back to the threshold when no target
is set. Nullable on purpose — most inventory (a drill, a couch) is not a
consumable, and NULL means "not tracked", never 0.

Additive columns only, so this applies and reverses cleanly. The DOWNGRADE
still needs the FK dance: dropping a column on SQLite REBUILDS the table, items
is FK-referenced (holdings, attachments, ...) and this app enforces foreign
keys — the exact hazard that wedged sibling migrations before.

Revision ID: 0016_consumables_policy
Revises: 0015_item_hidden_vault
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_consumables_policy"
down_revision = "0015_item_hidden_vault"
branch_labels = None
depends_on = None


def _columns(table) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for col in ("min_quantity", "target_quantity"):
        if col not in _columns("items"):
            op.add_column("items", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    present = [c for c in ("min_quantity", "target_quantity")
               if c in _columns("items")]
    if not present:
        return
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.get_context().autocommit_block():
            op.execute('DROP TABLE IF EXISTS "_alembic_tmp_items"')
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("items") as batch:
            for col in present:
                batch.drop_column(col)
    finally:
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
