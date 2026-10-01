"""Add durable Bridge delivery receipts.

Revision ID: e0f1a2b3c4d5
Revises: d9e8f7a6b5c4
"""

from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "d9e8f7a6b5c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Claim each message before sending it to a station."""
    op.create_table(
        "bridge_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent_slug", sa.String(100), nullable=False),
        sa.Column("submission_id", sa.String(160), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "agent_slug", "submission_id", name="uq_bridge_submission"),
    )


def downgrade() -> None:
    """Remove the receipt table only on an explicit migration rollback."""
    op.drop_table("bridge_submissions")
