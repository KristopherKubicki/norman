"""add console targets

Revision ID: c4a1f2b9d0e1
Revises: 2c1d7d94b0aa
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "c4a1f2b9d0e1"
down_revision = "2c1d7d94b0aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "console_targets" not in tables:
        op.create_table(
            "console_targets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column(
                "kind",
                sa.String(),
                nullable=False,
                server_default="tmux",
            ),
            sa.Column("socket_path", sa.String(), nullable=True),
            sa.Column("session_name", sa.String(), nullable=True),
            sa.Column("target", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "name", name="uq_console_target_user_name"),
        )

    try:
        indexes = {idx["name"] for idx in inspector.get_indexes("console_targets")}
    except Exception:
        indexes = set()
    if "ix_console_targets_user_id" not in indexes:
        op.create_index("ix_console_targets_user_id", "console_targets", ["user_id"])
    if "ix_console_targets_kind" not in indexes:
        op.create_index("ix_console_targets_kind", "console_targets", ["kind"])
    if "ix_console_targets_session_name" not in indexes:
        op.create_index(
            "ix_console_targets_session_name", "console_targets", ["session_name"]
        )


def downgrade() -> None:
    for idx in (
        "ix_console_targets_session_name",
        "ix_console_targets_kind",
        "ix_console_targets_user_id",
    ):
        try:
            op.drop_index(idx, table_name="console_targets")
        except Exception:
            pass
    try:
        op.drop_table("console_targets")
    except Exception:
        pass
