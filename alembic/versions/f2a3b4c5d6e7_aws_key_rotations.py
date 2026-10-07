"""Add durable AWS rotation state without enabling a write executor."""

from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    """Create encrypted state with no TTL or raw-reveal endpoint."""
    op.create_table(
        "aws_key_rotations",
        sa.Column("account_id", sa.String(12), primary_key=True),
        sa.Column("rotation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("old_key_id", sa.String(128), nullable=False),
        sa.Column("new_key_id", sa.String(128)),
        sa.Column("encrypted_credential", sa.Text()),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    """Never silently discard potentially unique credential recovery material."""
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM aws_key_rotations")).scalar()
    if count:
        raise RuntimeError("Reconcile AWS rotations before removing durable storage")
    op.drop_table("aws_key_rotations")
