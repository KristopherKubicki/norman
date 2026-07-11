"""add_routing_tables

Revision ID: 52c2c1e0e3aa
Revises: 426b64003873
Create Date: 2026-02-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "52c2c1e0e3aa"
down_revision = "426b64003873"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("connector_id", sa.Integer(), sa.ForeignKey("connectors.id")),
        sa.Column("connector_type", sa.String()),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id"), nullable=False),
        sa.Column("match_type", sa.String(), nullable=False, server_default="all"),
        sa.Column("match_value", sa.String()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index(
        "ix_routing_rules_user_id", "routing_rules", ["user_id"], unique=False
    )
    op.create_index(
        "ix_routing_rules_connector_id",
        "routing_rules",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        "ix_routing_rules_connector_type",
        "routing_rules",
        ["connector_type"],
        unique=False,
    )
    op.create_index(
        "ix_routing_rules_bot_id", "routing_rules", ["bot_id"], unique=False
    )

    op.create_table(
        "routing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("connector_id", sa.Integer(), sa.ForeignKey("connectors.id")),
        sa.Column("connector_type", sa.String()),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id")),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("routing_rules.id")),
        sa.Column("message_text", sa.String()),
        sa.Column("payload", sa.JSON()),
        sa.Column("status", sa.String(), nullable=False, server_default="received"),
        sa.Column(
            "delivery_status", sa.String(), nullable=False, server_default="skipped"
        ),
        sa.Column("error", sa.String()),
        sa.Column("delivery_error", sa.String()),
        sa.Column("idempotency_key", sa.String(), unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_routing_events_user_id", "routing_events", ["user_id"], unique=False
    )
    op.create_index(
        "ix_routing_events_connector_id",
        "routing_events",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        "ix_routing_events_connector_type",
        "routing_events",
        ["connector_type"],
        unique=False,
    )
    op.create_index(
        "ix_routing_events_bot_id", "routing_events", ["bot_id"], unique=False
    )
    op.create_index(
        "ix_routing_events_rule_id", "routing_events", ["rule_id"], unique=False
    )
    op.create_index(
        "ix_routing_events_idempotency_key",
        "routing_events",
        ["idempotency_key"],
        unique=True,
    )

    op.create_table(
        "routing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("routing_events.id")),
        sa.Column("connector_id", sa.Integer(), sa.ForeignKey("connectors.id")),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_error", sa.String()),
        sa.Column("payload", sa.JSON()),
        sa.Column("normalized", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index(
        "ix_routing_jobs_event_id", "routing_jobs", ["event_id"], unique=False
    )
    op.create_index(
        "ix_routing_jobs_connector_id", "routing_jobs", ["connector_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_routing_jobs_connector_id", table_name="routing_jobs")
    op.drop_index("ix_routing_jobs_event_id", table_name="routing_jobs")
    op.drop_table("routing_jobs")
    op.drop_index("ix_routing_events_idempotency_key", table_name="routing_events")
    op.drop_index("ix_routing_events_rule_id", table_name="routing_events")
    op.drop_index("ix_routing_events_bot_id", table_name="routing_events")
    op.drop_index("ix_routing_events_connector_type", table_name="routing_events")
    op.drop_index("ix_routing_events_connector_id", table_name="routing_events")
    op.drop_index("ix_routing_events_user_id", table_name="routing_events")
    op.drop_table("routing_events")
    op.drop_index("ix_routing_rules_bot_id", table_name="routing_rules")
    op.drop_index("ix_routing_rules_connector_type", table_name="routing_rules")
    op.drop_index("ix_routing_rules_connector_id", table_name="routing_rules")
    op.drop_index("ix_routing_rules_user_id", table_name="routing_rules")
    op.drop_table("routing_rules")
