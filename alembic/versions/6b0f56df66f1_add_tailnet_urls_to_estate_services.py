"""add tailnet urls to estate services

Revision ID: 6b0f56df66f1
Revises: e18f4b7c0d21
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "6b0f56df66f1"
down_revision = "e18f4b7c0d21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("estate_services"):
        return
    columns = {column["name"] for column in inspector.get_columns("estate_services")}
    if "web_url_tailnet" not in columns:
        op.add_column(
            "estate_services", sa.Column("web_url_tailnet", sa.String(), nullable=True)
        )
    if "console_url_tailnet" not in columns:
        op.add_column(
            "estate_services",
            sa.Column("console_url_tailnet", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("estate_services"):
        return
    columns = {column["name"] for column in inspector.get_columns("estate_services")}
    if "console_url_tailnet" in columns:
        op.drop_column("estate_services", "console_url_tailnet")
    if "web_url_tailnet" in columns:
        op.drop_column("estate_services", "web_url_tailnet")
