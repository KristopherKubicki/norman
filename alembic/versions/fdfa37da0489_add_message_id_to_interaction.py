"""add message_id to Interaction

Revision ID: fdfa37da0489
Revises: eacd88a5c06d
Create Date: 2024-08-21 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fdfa37da0489"
down_revision = "eacd88a5c06d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("interactions", sa.Column("message_id", sa.Integer(), nullable=False))
    op.create_foreign_key(None, "interactions", "messages", ["message_id"], ["id"])


def downgrade():
    op.drop_constraint(None, "interactions", type_="foreignkey")
    op.drop_column("interactions", "message_id")
