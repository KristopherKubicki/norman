"""add bridge conversations

Revision ID: d9e8f7a6b5c4
Revises: c8d7e6f5a4b3
"""

from alembic import op
import sqlalchemy as sa


revision = "d9e8f7a6b5c4"
down_revision = "c8d7e6f5a4b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bridge_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("principal_slug", sa.String(), nullable=False),
        sa.Column("domain_slug", sa.String(), nullable=False),
        sa.Column("direct_agent_slug", sa.String(), nullable=True),
        sa.Column("member_slugs_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "principal_slug",
            "direct_agent_slug",
            name="uq_bridge_conversations_direct_agent",
        ),
    )
    op.create_index("ix_bridge_conversations_id", "bridge_conversations", ["id"])
    op.create_index(
        "ix_bridge_conversations_user_id", "bridge_conversations", ["user_id"]
    )
    op.create_index(
        "ix_bridge_conversations_conversation_id",
        "bridge_conversations",
        ["conversation_id"],
        unique=True,
    )
    op.create_index("ix_bridge_conversations_kind", "bridge_conversations", ["kind"])
    op.create_index(
        "ix_bridge_conversations_principal_slug",
        "bridge_conversations",
        ["principal_slug"],
    )
    op.create_index(
        "ix_bridge_conversations_domain_slug",
        "bridge_conversations",
        ["domain_slug"],
    )
    op.create_index(
        "ix_bridge_conversations_direct_agent_slug",
        "bridge_conversations",
        ["direct_agent_slug"],
    )
    op.create_index(
        "ix_bridge_conversations_created_at",
        "bridge_conversations",
        ["created_at"],
    )
    op.create_index(
        "ix_bridge_conversations_updated_at",
        "bridge_conversations",
        ["updated_at"],
    )


def downgrade():
    op.drop_table("bridge_conversations")
