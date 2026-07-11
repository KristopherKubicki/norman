"""add console runtime tables

Revision ID: b7f3d2c9a4e1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7f3d2c9a4e1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_runtime_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("lease_json", sa.JSON(), nullable=True),
        sa.Column("checkpoints_json", sa.JSON(), nullable=True),
        sa.Column("artifacts_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_console_runtime_jobs_id", "console_runtime_jobs", ["id"])
    op.create_index("ix_console_runtime_jobs_user_id", "console_runtime_jobs", ["user_id"])
    op.create_index("ix_console_runtime_jobs_job_id", "console_runtime_jobs", ["job_id"])
    op.create_index("ix_console_runtime_jobs_status", "console_runtime_jobs", ["status"])
    op.create_index("ix_console_runtime_jobs_created_at", "console_runtime_jobs", ["created_at"])
    op.create_index("ix_console_runtime_jobs_updated_at", "console_runtime_jobs", ["updated_at"])

    op.create_table(
        "console_runtime_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("console_runtime_jobs.job_id"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column("detail", sa.String(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(), nullable=False, server_default="timeline"),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_console_runtime_events_job_sequence",
        ),
        sa.UniqueConstraint(
            "event_id",
            name="uq_console_runtime_events_event_id",
        ),
    )
    op.create_index("ix_console_runtime_events_id", "console_runtime_events", ["id"])
    op.create_index("ix_console_runtime_events_user_id", "console_runtime_events", ["user_id"])
    op.create_index("ix_console_runtime_events_job_id", "console_runtime_events", ["job_id"])
    op.create_index("ix_console_runtime_events_event_id", "console_runtime_events", ["event_id"])
    op.create_index("ix_console_runtime_events_sequence", "console_runtime_events", ["sequence"])
    op.create_index("ix_console_runtime_events_event_type", "console_runtime_events", ["event_type"])
    op.create_index("ix_console_runtime_events_category", "console_runtime_events", ["category"])
    op.create_index("ix_console_runtime_events_visibility", "console_runtime_events", ["visibility"])
    op.create_index("ix_console_runtime_events_created_at", "console_runtime_events", ["created_at"])


def downgrade():
    op.drop_index("ix_console_runtime_events_created_at", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_visibility", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_category", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_event_type", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_sequence", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_event_id", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_job_id", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_user_id", table_name="console_runtime_events")
    op.drop_index("ix_console_runtime_events_id", table_name="console_runtime_events")
    op.drop_table("console_runtime_events")
    op.drop_index("ix_console_runtime_jobs_updated_at", table_name="console_runtime_jobs")
    op.drop_index("ix_console_runtime_jobs_created_at", table_name="console_runtime_jobs")
    op.drop_index("ix_console_runtime_jobs_status", table_name="console_runtime_jobs")
    op.drop_index("ix_console_runtime_jobs_job_id", table_name="console_runtime_jobs")
    op.drop_index("ix_console_runtime_jobs_user_id", table_name="console_runtime_jobs")
    op.drop_index("ix_console_runtime_jobs_id", table_name="console_runtime_jobs")
    op.drop_table("console_runtime_jobs")
