"""users.password_changed_at + api_tokens.expires_at — credential lifecycle

password_changed_at: a JWT whose ``iat`` is older than this is refused, so a
password change signs out every other session. expires_at: an API key past
this instant is no longer a credential. Both nullable on purpose — NULL means
"never changed" / "never expires", which is exactly today's behaviour, so this
is a pure additive no-op on upgrade.

Plain ``DateTime`` (naive UTC), matching every other timestamp column — see
app/timeutil.py.

Idempotent (skips if present). The DOWNGRADE needs the FK dance: dropping a
column on SQLite REBUILDS the table, and users is FK-referenced by most of the
schema while this app enforces foreign keys — same hazard 0015/0016/0018 guard
against.

Revision ID: 0020_auth_lifecycle
Revises: 0019_quantity_numeric
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_auth_lifecycle"
down_revision = "0019_quantity_numeric"
branch_labels = None
depends_on = None

_COLUMNS = (("users", "password_changed_at"), ("api_tokens", "expires_at"))


def _columns(table) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, column in _COLUMNS:
        if column not in _columns(table):
            op.add_column(table, sa.Column(column, sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        if column not in _columns(table):
            continue
        is_sqlite = op.get_bind().dialect.name == "sqlite"
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute(f'DROP TABLE IF EXISTS "_alembic_tmp_{table}"')
                op.execute("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
        finally:
            if is_sqlite:
                with op.get_context().autocommit_block():
                    op.execute("PRAGMA foreign_keys=ON")
