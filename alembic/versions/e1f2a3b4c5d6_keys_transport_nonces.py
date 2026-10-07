"""Add replay protection for signed host requests."""

from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d9e8f7a6b5c4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "keys_transport_nonces",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_keys_transport_nonces_expires_at", "keys_transport_nonces", ["expires_at"])


def downgrade():
    op.drop_table("keys_transport_nonces")
