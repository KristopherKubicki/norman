"""add created_at index

Revision ID: 7ef8edb950cb
Revises: fdfa37da0489
Create Date: 2024-08-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7ef8edb950cb'
down_revision = 'fdfa37da0489'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])


def downgrade():
    op.drop_index('ix_messages_created_at', table_name='messages')
