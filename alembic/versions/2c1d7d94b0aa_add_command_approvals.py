"""Add command approvals table.

Revision ID: 2c1d7d94b0aa
Revises: 9b3c1b6e9f4a
Create Date: 2026-02-16

"""

from alembic import op
import sqlalchemy as sa


revision = "2c1d7d94b0aa"
down_revision = "9b3c1b6e9f4a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "command_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "connector_id",
            sa.Integer(),
            sa.ForeignKey("connectors.id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("routing_events.id"),
            nullable=True,
        ),
        sa.Column("command_text", sa.String(), nullable=False),
        sa.Column("command_class", sa.String(), nullable=False, server_default="change"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("confirm_token", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_command_approvals_user_id", "command_approvals", ["user_id"])
    op.create_index(
        "ix_command_approvals_connector_id", "command_approvals", ["connector_id"]
    )
    op.create_index("ix_command_approvals_event_id", "command_approvals", ["event_id"])
    op.create_index("ix_command_approvals_status", "command_approvals", ["status"])


def downgrade():
    try:
        op.drop_index("ix_command_approvals_status", table_name="command_approvals")
    except Exception:
        pass
    try:
        op.drop_index(
            "ix_command_approvals_event_id", table_name="command_approvals"
        )
    except Exception:
        pass
    try:
        op.drop_index(
            "ix_command_approvals_connector_id", table_name="command_approvals"
        )
    except Exception:
        pass
    try:
        op.drop_index("ix_command_approvals_user_id", table_name="command_approvals")
    except Exception:
        pass
    op.drop_table("command_approvals")
