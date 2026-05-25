"""add console url to estate services

Revision ID: e18f4b7c0d21
Revises: c4a1f2b9d0e1
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e18f4b7c0d21"
down_revision = "c4a1f2b9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("estate_services")}
    if "console_url" not in columns:
        op.add_column("estate_services", sa.Column("console_url", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("estate_services")}
    if "console_url" in columns:
        op.drop_column("estate_services", "console_url")
