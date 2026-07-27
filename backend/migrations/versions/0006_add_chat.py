"""add chat_sessions + chat_messages (assistant conversations)

Idempotent create: the 0001 metadata baseline builds these tables on fresh/adopted
DBs, so this delta only adds them to DBs stamped before the models existed.

Revision ID: 0006_add_chat
Revises: 0005_add_app_settings
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_add_chat"
down_revision = "0005_add_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "chat_sessions" not in tables:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False, server_default="New chat"),
            sa.Column("group_id", sa.String(36), sa.ForeignKey("groups.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_chat_sessions_group_id", "chat_sessions", ["group_id"])
    if "chat_messages" not in tables:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tool_trace", sa.Text(), nullable=False, server_default=""),
            sa.Column("session_id", sa.String(36),
                      sa.ForeignKey("chat_sessions.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "chat_messages" in tables:
        op.drop_table("chat_messages")
    if "chat_sessions" in tables:
        op.drop_table("chat_sessions")
