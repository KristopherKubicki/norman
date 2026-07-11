"""add channel messages

Revision ID: 8d3c8c1d2c1e
Revises: 52c2c1e0e3aa
Create Date: 2026-02-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "8d3c8c1d2c1e"
down_revision = "52c2c1e0e3aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "channel_messages" not in tables:
        op.create_table(
            "channel_messages",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "channel_id",
                sa.Integer(),
                sa.ForeignKey("channels.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("content", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="user"),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("channel_messages")}
    if "ix_channel_messages_channel_id" not in indexes:
        op.create_index(
            "ix_channel_messages_channel_id", "channel_messages", ["channel_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_channel_messages_channel_id", table_name="channel_messages")
    op.drop_table("channel_messages")
