"""add api_tokens.access (per-key access class: write | read)

Idempotent add-column with server_default 'write' so every EXISTING key keeps full
read+write ability (unchanged behaviour). `read` keys are read-only: the REST API
rejects non-GET/HEAD requests and the MCP guard rejects mutating tool calls.
Dialect-safe (SQLite + Postgres).

Revision ID: 0011_add_api_token_access
Revises: 0010_add_api_token_scope
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_add_api_token_access"
down_revision = "0010_add_api_token_scope"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def upgrade() -> None:
    if not _has_column("api_tokens", "access"):
        op.add_column(
            "api_tokens",
            sa.Column("access", sa.String(8), nullable=False, server_default="write"),
        )


def downgrade() -> None:
    if _has_column("api_tokens", "access"):
        with op.batch_alter_table("api_tokens") as batch:
            batch.drop_column("access")
