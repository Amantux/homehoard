"""unique per-group asset_id (de-dup existing, then partial unique index)

A bare max(asset_id)+1 allocation races two concurrent item creates to the same
per-group asset id. This adds a partial UNIQUE(group_id, asset_id) WHERE asset_id>0
so the DB enforces the invariant (create_item retries on the conflict). Existing
DBs may already hold duplicates from past races, so we renumber those first — the
oldest row keeps its id, later duplicates move to the group's next free id.

Partial (asset_id > 0) so the many imported items left at the 0 "unassigned"
sentinel aren't collapsed. Fresh DBs already have the index from the 0001 metadata
baseline (it's in the model's __table_args__), so the create here is guarded.

Revision ID: 0004_uq_items_group_asset
Revises: 0003_add_item_barcode
Create Date: 2026-07-26
"""
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0004_uq_items_group_asset"
down_revision = "0003_add_item_barcode"
branch_labels = None
depends_on = None

_INDEX = "uq_items_group_asset"


def _dedupe_asset_ids(conn) -> None:
    """Renumber duplicate (group_id, asset_id>0) rows in place. Re-runnable: a second
    pass finds no duplicates and does nothing."""
    rows = conn.execute(sa.text(
        "SELECT id, group_id, asset_id FROM items WHERE asset_id > 0 "
        "ORDER BY group_id, asset_id, created_at, id"
    )).fetchall()
    group_max = defaultdict(int)
    for _id, gid, aid in rows:
        if aid > group_max[gid]:
            group_max[gid] = aid
    seen = set()
    for _id, gid, aid in rows:
        key = (gid, aid)
        if key in seen:
            group_max[gid] += 1
            conn.execute(sa.text("UPDATE items SET asset_id = :a WHERE id = :i"),
                         {"a": group_max[gid], "i": _id})
        else:
            seen.add(key)


def _index_exists(conn, name) -> bool:
    """Reliable across engines. get_indexes() doesn't reflect SQLite PARTIAL indexes,
    and swallowing a duplicate-index error would poison a Postgres transaction, so
    check the catalog directly instead."""
    if conn.dialect.name == "sqlite":
        q = "SELECT 1 FROM sqlite_master WHERE type='index' AND name = :n"
    else:  # postgresql
        q = "SELECT 1 FROM pg_indexes WHERE indexname = :n"
    return conn.execute(sa.text(q), {"n": name}).first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    _dedupe_asset_ids(conn)
    # A fresh DB already has this index from the 0001 metadata baseline; only add it
    # to DBs stamped before it existed.
    if not _index_exists(conn, _INDEX):
        op.create_index(
            _INDEX, "items", ["group_id", "asset_id"], unique=True,
            sqlite_where=sa.text("asset_id > 0"),
            postgresql_where=sa.text("asset_id > 0"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _index_exists(conn, _INDEX):
        op.drop_index(_INDEX, table_name="items")
