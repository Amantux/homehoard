"""chat_sessions.awaiting_vault_phrase: server-side vault-phrase short-circuit

When the assistant's unhide_items tool answers {needsPassphrase: true}, the
session is flagged so the NEXT inbound message (the passphrase) is intercepted
server-side — never sent to the LLM provider, never stored in history.

`server_default` so a database built by `create_all()` and one built by
migrations describe the same schema. Idempotent, with a real downgrade.

Revision ID: 0017_chat_awaiting_vault
Revises: 0016_consumables_policy
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_chat_awaiting_vault"
down_revision = "0016_consumables_policy"
branch_labels = None
depends_on = None


def _columns(table) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "awaiting_vault_phrase" not in _columns("chat_sessions"):
        op.add_column("chat_sessions", sa.Column(
            "awaiting_vault_phrase", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    # SQLite drops a column by REBUILDING the table; chat_sessions is
    # FK-referenced by chat_messages and this app enforces foreign keys, so the
    # rebuild's table-drop fails on a populated database. Suspend enforcement
    # around it (the PRAGMA is a no-op inside a transaction, hence
    # autocommit_block) — same pattern as 0015.
    if is_sqlite:
        with op.get_context().autocommit_block():
            op.execute('DROP TABLE IF EXISTS "_alembic_tmp_chat_sessions"')
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        if "awaiting_vault_phrase" in _columns("chat_sessions"):
            with op.batch_alter_table("chat_sessions") as batch:
                batch.drop_column("awaiting_vault_phrase")
    finally:
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
