"""quantity columns Float -> Numeric(12, 3)

items.quantity / min_quantity / target_quantity and item_holdings.quantity were
binary floats, so holdings of 0.1 + 0.2 summed to 0.30000000000000004 and
restock thresholds compared against drifted totals. Numeric(12, 3) stores them
exactly (3 decimals, 9 integer digits — the API refuses anything finer).

Postgres: ALTER COLUMN ... TYPE numeric(12,3) needs no USING — float8 -> numeric
is an assignment cast (and numeric -> float8 implicit for the downgrade). Values
with more than 3 decimals are rounded once, here. No server_default: none of
these columns had one (Item.quantity's default=1 is Python-side), so create_all
and migrated databases still agree.

SQLite: the type change REBUILDS both tables. items is FK-referenced by half the
schema and this app enforces foreign keys, so the rebuild runs with
foreign_keys=OFF — the same dance as 0016/0018's downgrades. Idempotent: a
column already of the target type is skipped.

Revision ID: 0019_quantity_numeric
Revises: 0018_maintenance_recurrence
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_quantity_numeric"
down_revision = "0018_maintenance_recurrence"
branch_labels = None
depends_on = None

_COLUMNS = {
    # (column, existing nullable) — quantity is NOT NULL (non-Optional Mapped).
    "items": [("quantity", False), ("min_quantity", True), ("target_quantity", True)],
    "item_holdings": [("quantity", False)],
}


def _numeric_columns(table) -> dict:
    """{column name: True if it is currently Numeric (not Float)}."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return {}
    return {c["name"]: (isinstance(c["type"], sa.Numeric)
                        and not isinstance(c["type"], sa.Float))
            for c in insp.get_columns(table)}


def _convert(to_numeric: bool) -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    new_type = sa.Numeric(12, 3) if to_numeric else sa.Float()
    old_type = sa.Float() if to_numeric else sa.Numeric(12, 3)
    for table, cols in _COLUMNS.items():
        current = _numeric_columns(table)
        todo = [(c, nullable) for c, nullable in cols
                if c in current and current[c] != to_numeric]
        if not todo:
            continue
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute(f'DROP TABLE IF EXISTS "_alembic_tmp_{table}"')
                op.execute("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table(table) as batch:
                for col, nullable in todo:
                    batch.alter_column(col, type_=new_type, existing_type=old_type,
                                       existing_nullable=nullable)
        finally:
            if is_sqlite:
                with op.get_context().autocommit_block():
                    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _convert(to_numeric=True)


def downgrade() -> None:
    _convert(to_numeric=False)
