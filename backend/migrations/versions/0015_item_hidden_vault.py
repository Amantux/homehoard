"""vault mode: items.hidden, groups.vault_passphrase_hash, vault_unlocks

Hidden items are invisible on every read surface until the caller's session is
unlocked with the household passphrase. `hidden` is deliberately separate from
`archived`: archived means "disposed / long-term storage" and is merely filtered
out of the default list, while hidden means "do not surface this anywhere".

`hidden` is indexed because it lands in the WHERE clause of essentially every
item read. Both new columns carry a server_default so a database built by
`create_all()` and one built by migrations describe the same schema — the
divergence class that 0013/0015 in the sibling app exist to prevent.

Idempotent (skips anything already present, so a fresh metadata-baseline DB
migrates cleanly) with a real downgrade.

Revision ID: 0015_item_hidden_vault
Revises: 0014_money_numeric
Create Date: 2026-08-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_item_hidden_vault"
down_revision = "0014_money_numeric"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set:
    return set(_inspector().get_table_names())


def _columns(table) -> set:
    if table not in _tables():
        return set()
    return {c["name"] for c in _inspector().get_columns(table)}


def _indexes(table) -> set:
    if table not in _tables():
        return set()
    return {ix["name"] for ix in _inspector().get_indexes(table)}


def upgrade() -> None:
    if "hidden" not in _columns("items"):
        op.add_column("items", sa.Column(
            "hidden", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))
    if "ix_items_hidden" not in _indexes("items"):
        op.create_index("ix_items_hidden", "items", ["hidden"])

    if "vault_passphrase_hash" not in _columns("groups"):
        op.add_column("groups", sa.Column(
            "vault_passphrase_hash", sa.String(length=255),
            nullable=False, server_default=""))

    if "vault_unlocks" not in _tables():
        op.create_table(
            "vault_unlocks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("group_id", sa.String(length=36),
                      sa.ForeignKey("groups.id"), nullable=True),
            sa.Column("user_id", sa.String(length=36),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("credential_fingerprint", sa.String(length=64),
                      nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_vault_unlocks_group_id", "vault_unlocks", ["group_id"])
        op.create_index("ix_vault_unlocks_credential_fingerprint",
                        "vault_unlocks", ["credential_fingerprint"])


def downgrade() -> None:
    if "vault_unlocks" in _tables():
        op.drop_table("vault_unlocks")

    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    # SQLite drops a column by REBUILDING the table, and this app enforces
    # foreign keys — items and groups are both FK-referenced, so the rebuild's
    # table-drop fails on a populated database and leaves an _alembic_tmp corpse
    # that wedges the next boot. Suspend enforcement around it; the PRAGMA is a
    # no-op inside a transaction, hence autocommit_block.
    if is_sqlite:
        with op.get_context().autocommit_block():
            for table in ("items", "groups"):
                op.execute(f'DROP TABLE IF EXISTS "_alembic_tmp_{table}"')
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        if "ix_items_hidden" in _indexes("items"):
            op.drop_index("ix_items_hidden", table_name="items")
        if "hidden" in _columns("items"):
            with op.batch_alter_table("items") as batch:
                batch.drop_column("hidden")
        if "vault_passphrase_hash" in _columns("groups"):
            with op.batch_alter_table("groups") as batch:
                batch.drop_column("vault_passphrase_hash")
    finally:
        if is_sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
