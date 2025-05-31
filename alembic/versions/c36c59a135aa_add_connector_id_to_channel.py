"""add connector_id to channels

Revision ID: c36c59a135aa
Revises: eacd88a5c06d
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c36c59a135aa'
down_revision = 'eacd88a5c06d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('channels', sa.Column('connector_id', sa.Integer(), nullable=False))
    op.create_foreign_key(None, 'channels', 'connectors', ['connector_id'], ['id'])


def downgrade():
    op.drop_constraint(None, 'channels', type_='foreignkey')
    op.drop_column('channels', 'connector_id')
