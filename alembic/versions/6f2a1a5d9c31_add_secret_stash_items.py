"""add secret stash items

Revision ID: 6f2a1a5d9c31
Revises: f3e5c4a1b2d0
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f2a1a5d9c31"
down_revision = "f3e5c4a1b2d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_stash_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pointer_token", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("masked_preview", sa.String(), nullable=False, server_default=""),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_secret_stash_items_id", "secret_stash_items", ["id"])
    op.create_index(
        "ix_secret_stash_items_pointer_token",
        "secret_stash_items",
        ["pointer_token"],
        unique=True,
    )
    op.create_index("ix_secret_stash_items_user_id", "secret_stash_items", ["user_id"])
    op.create_index(
        "ix_secret_stash_items_channel_id", "secret_stash_items", ["channel_id"]
    )
    op.create_index("ix_secret_stash_items_source", "secret_stash_items", ["source"])
    op.create_index("ix_secret_stash_items_status", "secret_stash_items", ["status"])
    op.create_index(
        "ix_secret_stash_items_expires_at", "secret_stash_items", ["expires_at"]
    )
    op.create_index(
        "ix_secret_stash_items_revoked_by", "secret_stash_items", ["revoked_by"]
    )


def downgrade():
    op.drop_index("ix_secret_stash_items_revoked_by", table_name="secret_stash_items")
    op.drop_index("ix_secret_stash_items_expires_at", table_name="secret_stash_items")
    op.drop_index("ix_secret_stash_items_status", table_name="secret_stash_items")
    op.drop_index("ix_secret_stash_items_source", table_name="secret_stash_items")
    op.drop_index("ix_secret_stash_items_channel_id", table_name="secret_stash_items")
    op.drop_index("ix_secret_stash_items_user_id", table_name="secret_stash_items")
    op.drop_index(
        "ix_secret_stash_items_pointer_token", table_name="secret_stash_items"
    )
    op.drop_index("ix_secret_stash_items_id", table_name="secret_stash_items")
    op.drop_table("secret_stash_items")
