"""add enabled fields to bot and connector

Revision ID: add_enabled_fields
Revises: fdfa37da0489
Create Date: 2024-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_enabled_fields'
down_revision = 'fdfa37da0489'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('bots', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('connectors', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('bots', 'enabled')
    op.drop_column('connectors', 'enabled')
