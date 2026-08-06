"""money columns: Float -> Numeric(12, 2)

`items.purchase_price`, `items.sold_price` and `maintenance_entries.cost` were
`Float`. The house rule is that money is `Numeric` — floats touching money are a
blocker — and the sibling Edibl app has stored money as `Numeric(10, 2)` from the
start with an explicit "Decimal, never float" comment.

Honest framing: no user-visible drift was reproducible at household scale (2000
random inventories of 20-300 items produced no difference at 2dp; float64 has
~15 significant digits). This is standards compliance and cross-app consistency,
not a bug fix.

Widening a float to a fixed-point decimal is lossless for every value that a
2dp price can hold, so no data is rounded away going up. The downgrade is the
lossy direction and is written for real anyway, because a silently wrong
downgrade is worse than none.

SQLite cannot ALTER a column type in place, so this runs inside a batch
operation, which Alembic implements as a table rebuild; on PostgreSQL these are
plain ALTERs with a USING cast. Idempotent: re-running after a partial failure
checks the current type first.

Revision ID: 0014_money_numeric
Revises: 0013_attachment_title
Create Date: 2026-08-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_money_numeric"
down_revision = "0013_attachment_title"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)

# table -> columns that hold money
_COLUMNS = {
    "items": ("purchase_price", "sold_price"),
    "maintenance_entries": ("cost",),
}


def _column_type(table, column):
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return None
    for c in insp.get_columns(table):
        if c["name"] == column:
            return str(c["type"]).upper()
    return None


def _convert(to_numeric: bool) -> None:
    want = "NUMERIC" if to_numeric else "FLOAT"
    new_type = MONEY if to_numeric else sa.Float()
    old_type = sa.Float() if to_numeric else MONEY
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"

    if sqlite:
        # A batch alter on SQLite is a table REBUILD: create a temp table, copy,
        # DROP the original, rename. `maintenance_entries.item_id` references
        # `items.id`, and this app turns FK enforcement ON (extensions.py), so
        # dropping `items` raises "FOREIGN KEY constraint failed" the moment the
        # database has any data in it. An empty database migrates fine, which is
        # exactly why this was invisible until a seeded fixture was tried.
        #
        # Clean up a temp table left by a previous half-finished attempt too,
        # otherwise the retry dies with "table _alembic_tmp_items already
        # exists" — which is what "idempotent" has to mean here.
        for table in _COLUMNS:
            op.execute(f'DROP TABLE IF EXISTS "_alembic_tmp_{table}"')
        op.execute("PRAGMA foreign_keys=OFF")
    try:
        for table, columns in _COLUMNS.items():
            todo = [c for c in columns if _column_type(table, c) is not None
                    and want not in (_column_type(table, c) or "")]
            if not todo:
                continue
            with op.batch_alter_table(table) as batch:
                for column in todo:
                    batch.alter_column(
                        column,
                        existing_type=old_type,
                        type_=new_type,
                        existing_nullable=True,
                        # Postgres needs to be told how to reinterpret the
                        # values; SQLite ignores this because batch mode
                        # rebuilds the table.
                        postgresql_using=f"{column}::numeric(12,2)" if to_numeric
                        else f"{column}::double precision",
                    )
    finally:
        if sqlite:
            op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _convert(to_numeric=True)


def downgrade() -> None:
    # Lossy in principle (a decimal that no float represents exactly), but every
    # value a 2dp price column can hold round-trips through float64 fine.
    _convert(to_numeric=False)
