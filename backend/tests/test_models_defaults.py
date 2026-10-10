"""Boolean server defaults must be portable across dialects.

`server_default=text("0")` renders `DEFAULT 0` everywhere, which Postgres rejects
for a BOOLEAN column ("default expression is of type integer"). `sa.false()`
renders `false` on Postgres and `0` on SQLite.
"""
import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.models.chat import ChatSession
from app.models.item import Item

BOOL_DEFAULTS = [
    (Item.__table__, "hidden"),
    (ChatSession.__table__, "awaiting_vault_phrase"),
]


def _column_ddl(table, column, dialect):
    ddl = str(CreateTable(table).compile(dialect=dialect))
    line = next(ln for ln in ddl.splitlines() if ln.strip().startswith(column + " "))
    return line.strip().rstrip(",")


@pytest.mark.parametrize("table,column", BOOL_DEFAULTS)
def test_boolean_default_renders_false_on_postgres(table, column):
    line = _column_ddl(table, column, postgresql.dialect())
    assert "DEFAULT false" in line, line


@pytest.mark.parametrize("table,column", BOOL_DEFAULTS)
def test_boolean_default_renders_zero_on_sqlite(table, column):
    line = _column_ddl(table, column, sqlite.dialect())
    assert "DEFAULT (0)" in line or "DEFAULT 0" in line, line


def test_no_boolean_server_default_renders_integer_on_postgres():
    """Sweep every Boolean column, so a future `text("0")` default is caught too."""
    import app.models  # noqa: F401  (registers every model on the metadata)
    from sqlalchemy import Boolean

    from app.extensions import db

    checked = []
    for table in db.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, Boolean) and col.server_default is not None:
                line = _column_ddl(table, col.name, postgresql.dialect())
                assert "DEFAULT 0" not in line and "DEFAULT 1" not in line, line
                checked.append(col.name)
    assert {"hidden", "awaiting_vault_phrase"} <= set(checked)
