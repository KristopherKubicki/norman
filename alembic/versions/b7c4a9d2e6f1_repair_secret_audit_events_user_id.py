"""repair secret audit event user_id column

Revision ID: b7c4a9d2e6f1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31 01:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c4a9d2e6f1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    columns = sa.inspect(bind).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    indexes = sa.inspect(bind).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def upgrade():
    bind = op.get_bind()
    table_name = "secret_audit_events"
    index_name = "ix_secret_audit_events_user_id"
    if not _table_exists(bind, table_name):
        return
    if not _column_exists(bind, table_name, "user_id"):
        op.add_column(table_name, sa.Column("user_id", sa.Integer(), nullable=True))
    if not _index_exists(bind, table_name, index_name):
        op.create_index(index_name, table_name, ["user_id"])


def downgrade():
    bind = op.get_bind()
    table_name = "secret_audit_events"
    index_name = "ix_secret_audit_events_user_id"
    if not _table_exists(bind, table_name):
        return
    if _index_exists(bind, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)
    if _column_exists(bind, table_name, "user_id"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("user_id")
