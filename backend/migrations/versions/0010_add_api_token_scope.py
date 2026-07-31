"""add api_tokens.scope (per-key access scope: full | rest | mcp)

Idempotent add-column with server_default 'full' so every EXISTING key keeps full
REST access (unchanged behaviour). New scopes: `rest` (REST only, no MCP) and `mcp`
(MCP transport only, rejected at the REST API). Dialect-safe (SQLite + Postgres).

Revision ID: 0010_add_api_token_scope
Revises: 0009_add_ai_suggestions
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_add_api_token_scope"
down_revision = "0009_add_ai_suggestions"
branch_labels = None
depends_on = None


def _has_column(table, column) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {
        c["name"] for c in insp.get_columns(table)
    }


def upgrade() -> None:
    if not _has_column("api_tokens", "scope"):
        op.add_column(
            "api_tokens",
            sa.Column("scope", sa.String(16), nullable=False, server_default="full"),
        )


def downgrade() -> None:
    if _has_column("api_tokens", "scope"):
        with op.batch_alter_table("api_tokens") as batch:
            batch.drop_column("scope")
