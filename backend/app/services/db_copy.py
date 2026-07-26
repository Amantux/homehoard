"""Faithful whole-database copy between engines — for the SQLite -> Postgres
migration.

Every table uses a UUID string PK, so a straight FK-ordered row copy preserves
ids and relationships with no sequence resets. Copies into an EMPTY target only,
in a single transaction (all-or-nothing), and never modifies the source.
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, func, select

from ..config import Config
from ..extensions import db

_LOGGER = logging.getLogger("homehoard.db_copy")


class DbCopyError(Exception):
    """A migration precondition failed or the copy could not complete."""


class TargetNotEmpty(DbCopyError):
    """The destination database already contains rows — refuse to clobber it."""


class SourceUnreadable(DbCopyError):
    """The source database could not be read."""


def _dispose(*engines):
    for e in engines:
        try:
            e.dispose()
        except Exception:  # noqa: BLE001
            pass


def _order_for_self_fk(table, rows):
    """Order rows parent-before-child for any self-referential FK (e.g.
    locations.parent_id -> locations.id, items.parent_id, labels.parent_id).
    Postgres enforces FKs per row on insert, so a child stored physically before
    its parent would be rejected. No-op for tables without a self-FK; cross-table
    FK order is handled by sorted_tables."""
    self_cols = [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]
    if not self_cols or len(rows) < 2:
        return rows
    pk = list(table.primary_key.columns)[0].name
    by_id = {r[pk]: r for r in rows}
    emitted, ordered = set(), []

    def emit(r, seen):
        rid = r[pk]
        if rid in emitted or rid in seen:  # seen = cycle guard (trees have none)
            return
        seen.add(rid)
        for col in self_cols:
            pid = r.get(col)
            if pid is not None and pid in by_id:
                emit(by_id[pid], seen)
        emitted.add(rid)
        ordered.append(r)

    for r in rows:
        emit(r, set())
    return ordered


def _non_null_fallback(column):
    """A non-NULL value for a NOT NULL column whose source value is NULL — e.g. rows
    predating an added column (barcode, search_text) hold NULL in SQLite while the
    target schema built from the models declares the column NOT NULL."""
    import decimal

    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        return default.arg
    try:
        pytype = column.type.python_type
    except (NotImplementedError, AttributeError):
        return None
    if pytype is bool:
        return False
    if pytype is str:
        return ""
    if pytype in (int, float, decimal.Decimal):
        return 0
    # Unknown type (e.g. datetime): don't inject a wrong-typed "" — leave NULL so a
    # genuinely-required value fails loudly rather than corrupting silently.
    return None


def _dedupe_item_asset_ids(rows):
    """Renumber duplicate (group_id, asset_id>0) item rows in place — later duplicates
    move to the group's next free id — so a copy into a target carrying the partial
    UNIQUE(group_id, asset_id) index can't fail. Mirrors migration 0004's repair."""
    from collections import defaultdict

    group_max = defaultdict(int)
    for r in rows:
        aid = r.get("asset_id") or 0
        if aid > group_max[r.get("group_id")]:
            group_max[r.get("group_id")] = aid
    seen = set()
    for r in rows:
        aid = r.get("asset_id") or 0
        if aid <= 0:
            continue  # the 0 "unassigned" sentinel isn't covered by the partial index
        key = (r.get("group_id"), aid)
        if key in seen:
            group_max[r.get("group_id")] += 1
            r["asset_id"] = group_max[r.get("group_id")]
        else:
            seen.add(key)


def _coerce_non_null(table, rows):
    """In place: fill NULLs in NOT NULL columns so the copy into a stricter target
    schema doesn't fail with a NotNullViolation. Only touches columns that are both
    NOT NULL and actually NULL in the source (PKs/FKs always carry a value)."""
    cols = [c for c in table.columns if not c.nullable]
    for row in rows:
        for c in cols:
            if row.get(c.name) is None:
                row[c.name] = _non_null_fallback(c)


def copy_database(source_url: str, target_url: str) -> dict:
    """Copy every table from ``source_url`` into ``target_url`` (which must be
    EMPTY). Returns ``{"ok": True, "tables": {name: count}, "total": n}``.

    Raises ``TargetNotEmpty`` if the destination already has data (never clobbers),
    ``SourceUnreadable`` if the source can't be read, ``DbCopyError`` on a
    post-copy row-count mismatch. ``alembic_version`` is not part of the model
    metadata, so it isn't copied — the target is stamped to baseline by the normal
    startup adoption path on first boot.
    """
    from .. import models  # noqa: F401 - ensure every table is registered on db.metadata

    target_url = Config._normalize_db_url(target_url.strip())
    source = create_engine(source_url)
    # Bound the connect so an unreachable Postgres fails fast instead of hanging
    # the request / startup. (connect_timeout is a libpq arg — Postgres only.)
    target_kwargs = ({"connect_args": {"connect_timeout": 10}}
                     if target_url.startswith("postgresql") else {})
    target = create_engine(target_url, **target_kwargs)
    tables = list(db.metadata.sorted_tables)
    try:
        db.metadata.create_all(target)  # idempotent; schema matches the models

        # Refuse a non-empty target — migrate only into an empty database.
        with target.connect() as tconn:
            for t in tables:
                if tconn.execute(select(func.count()).select_from(t)).scalar():
                    raise TargetNotEmpty(
                        f"the target database already has rows in {t.name!r}; "
                        "migrate only into an empty database"
                    )

        # Read all source rows (typed, so bool/datetime/JSON convert correctly),
        # then insert in FK order inside one transaction — all-or-nothing.
        try:
            with source.connect() as sconn:
                data = {t.name: [dict(r) for r in sconn.execute(select(t)).mappings()]
                        for t in tables}
        except Exception as exc:  # noqa: BLE001
            raise SourceUnreadable(str(exc)) from exc

        # A column added by a later migration is NULL on pre-existing source rows,
        # but the target schema (from the models) declares it NOT NULL — fill those.
        for t in tables:
            _coerce_non_null(t, data[t.name])
        # The target schema carries the partial UNIQUE(group_id, asset_id) index, but a
        # legacy source may hold duplicate asset_ids from past races (the same thing
        # migration 0004 repairs). De-dup the rows in memory or the copy would fail.
        _dedupe_item_asset_ids(data.get("items", []))

        # Insert AND verify inside one transaction, so a per-row FK/type rejection
        # or a count mismatch rolls the whole copy back — all-or-nothing.
        counts = {}
        with target.begin() as tconn:
            for t in tables:
                rows = _order_for_self_fk(t, data[t.name])
                if rows:
                    tconn.execute(t.insert(), rows)
                counts[t.name] = len(rows)
            for t in tables:
                got = tconn.execute(select(func.count()).select_from(t)).scalar()
                if got != counts[t.name]:
                    raise DbCopyError(
                        f"row-count mismatch on {t.name!r}: copied {counts[t.name]}, "
                        f"target has {got}"
                    )

        total = sum(counts.values())
        _LOGGER.info("Copied %d rows across %d tables to the target database",
                     total, len(tables))
        return {"ok": True, "tables": counts, "total": total}
    finally:
        _dispose(source, target)


def migrate_sqlite_to_postgres(source_url: str, target_url: str) -> dict:
    """``copy_database`` with the SQLite -> Postgres policy enforced."""
    norm = Config._normalize_db_url(target_url.strip())
    if not source_url.startswith("sqlite"):
        raise DbCopyError("the migration source must be the built-in SQLite database")
    if not norm.startswith("postgresql"):
        raise DbCopyError(
            "the migration target must be a postgresql:// URL "
            "(e.g. postgresql+psycopg://user:pass@host:5432/dbname)"
        )
    return copy_database(source_url, norm)
