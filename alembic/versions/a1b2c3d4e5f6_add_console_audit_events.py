"""add console audit events

Revision ID: a1b2c3d4e5f6
Revises: 6f2a1a5d9c31
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "6f2a1a5d9c31"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "connector_id", sa.Integer(), sa.ForeignKey("connectors.id"), nullable=False
        ),
        sa.Column("connector_name", sa.String(), nullable=False, server_default=""),
        sa.Column("session_name", sa.String(), nullable=False, server_default=""),
        sa.Column("agent_name", sa.String(), nullable=False, server_default=""),
        sa.Column("host_name", sa.String(), nullable=False, server_default=""),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("actor_ip", sa.String(), nullable=True),
        sa.Column("thread_id", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "connector_id",
            "source_event_id",
            name="uq_console_audit_events_connector_source_event",
        ),
    )
    op.create_index("ix_console_audit_events_id", "console_audit_events", ["id"])
    op.create_index(
        "ix_console_audit_events_user_id", "console_audit_events", ["user_id"]
    )
    op.create_index(
        "ix_console_audit_events_connector_id",
        "console_audit_events",
        ["connector_id"],
    )
    op.create_index(
        "ix_console_audit_events_session_name",
        "console_audit_events",
        ["session_name"],
    )
    op.create_index(
        "ix_console_audit_events_agent_name", "console_audit_events", ["agent_name"]
    )
    op.create_index(
        "ix_console_audit_events_host_name", "console_audit_events", ["host_name"]
    )
    op.create_index(
        "ix_console_audit_events_event_type", "console_audit_events", ["event_type"]
    )
    op.create_index(
        "ix_console_audit_events_severity", "console_audit_events", ["severity"]
    )
    op.create_index(
        "ix_console_audit_events_thread_id", "console_audit_events", ["thread_id"]
    )
    op.create_index(
        "ix_console_audit_events_event_at", "console_audit_events", ["event_at"]
    )
    op.create_index(
        "ix_console_audit_events_collected_at",
        "console_audit_events",
        ["collected_at"],
    )


def downgrade():
    op.drop_index("ix_console_audit_events_collected_at", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_event_at", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_thread_id", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_severity", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_event_type", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_host_name", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_agent_name", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_session_name", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_connector_id", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_user_id", table_name="console_audit_events")
    op.drop_index("ix_console_audit_events_id", table_name="console_audit_events")
    op.drop_table("console_audit_events")
