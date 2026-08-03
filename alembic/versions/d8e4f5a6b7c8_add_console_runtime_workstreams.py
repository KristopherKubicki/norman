"""add console runtime workstreams

Revision ID: d8e4f5a6b7c8
Revises: b7f3d2c9a4e1
Create Date: 2026-07-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d8e4f5a6b7c8"
down_revision = "b7f3d2c9a4e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "console_runtime_jobs",
        sa.Column("workstream_id", sa.String(), nullable=True),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("parent_job_id", sa.String(), nullable=True),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("result_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_console_runtime_jobs_workstream_id",
        "console_runtime_jobs",
        ["workstream_id"],
    )
    op.create_index(
        "ix_console_runtime_jobs_parent_job_id",
        "console_runtime_jobs",
        ["parent_job_id"],
    )
    op.create_index(
        "ix_console_runtime_jobs_cancel_requested_at",
        "console_runtime_jobs",
        ["cancel_requested_at"],
    )

    op.create_table(
        "console_runtime_workstreams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workstream_id", sa.String(), nullable=False, unique=True),
        sa.Column(
            "coordinator_job_id",
            sa.String(),
            sa.ForeignKey("console_runtime_jobs.job_id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "coordinator_job_id",
            name="uq_console_runtime_workstreams_coordinator_job",
        ),
    )
    op.create_index(
        "ix_console_runtime_workstreams_id",
        "console_runtime_workstreams",
        ["id"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_user_id",
        "console_runtime_workstreams",
        ["user_id"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_workstream_id",
        "console_runtime_workstreams",
        ["workstream_id"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_coordinator_job_id",
        "console_runtime_workstreams",
        ["coordinator_job_id"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_status",
        "console_runtime_workstreams",
        ["status"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_created_at",
        "console_runtime_workstreams",
        ["created_at"],
    )
    op.create_index(
        "ix_console_runtime_workstreams_updated_at",
        "console_runtime_workstreams",
        ["updated_at"],
    )

    op.create_table(
        "console_runtime_job_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workstream_id",
            sa.String(),
            sa.ForeignKey("console_runtime_workstreams.workstream_id"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("console_runtime_jobs.job_id"),
            nullable=False,
        ),
        sa.Column(
            "depends_on_job_id",
            sa.String(),
            sa.ForeignKey("console_runtime_jobs.job_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "job_id",
            "depends_on_job_id",
            name="uq_console_runtime_job_dependencies_pair",
        ),
    )
    op.create_index(
        "ix_console_runtime_job_dependencies_id",
        "console_runtime_job_dependencies",
        ["id"],
    )
    op.create_index(
        "ix_console_runtime_job_dependencies_user_id",
        "console_runtime_job_dependencies",
        ["user_id"],
    )
    op.create_index(
        "ix_console_runtime_job_dependencies_workstream_id",
        "console_runtime_job_dependencies",
        ["workstream_id"],
    )
    op.create_index(
        "ix_console_runtime_job_dependencies_job_id",
        "console_runtime_job_dependencies",
        ["job_id"],
    )
    op.create_index(
        "ix_console_runtime_job_dependencies_depends_on_job_id",
        "console_runtime_job_dependencies",
        ["depends_on_job_id"],
    )


def downgrade():
    op.drop_index(
        "ix_console_runtime_job_dependencies_depends_on_job_id",
        table_name="console_runtime_job_dependencies",
    )
    op.drop_index(
        "ix_console_runtime_job_dependencies_job_id",
        table_name="console_runtime_job_dependencies",
    )
    op.drop_index(
        "ix_console_runtime_job_dependencies_workstream_id",
        table_name="console_runtime_job_dependencies",
    )
    op.drop_index(
        "ix_console_runtime_job_dependencies_user_id",
        table_name="console_runtime_job_dependencies",
    )
    op.drop_index(
        "ix_console_runtime_job_dependencies_id",
        table_name="console_runtime_job_dependencies",
    )
    op.drop_table("console_runtime_job_dependencies")
    op.drop_index(
        "ix_console_runtime_workstreams_updated_at",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_created_at",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_status",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_coordinator_job_id",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_workstream_id",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_user_id",
        table_name="console_runtime_workstreams",
    )
    op.drop_index(
        "ix_console_runtime_workstreams_id",
        table_name="console_runtime_workstreams",
    )
    op.drop_table("console_runtime_workstreams")
    op.drop_index(
        "ix_console_runtime_jobs_cancel_requested_at",
        table_name="console_runtime_jobs",
    )
    op.drop_index(
        "ix_console_runtime_jobs_parent_job_id",
        table_name="console_runtime_jobs",
    )
    op.drop_index(
        "ix_console_runtime_jobs_workstream_id",
        table_name="console_runtime_jobs",
    )
    op.drop_column("console_runtime_jobs", "cancel_requested_at")
    op.drop_column("console_runtime_jobs", "result_json")
    op.drop_column("console_runtime_jobs", "parent_job_id")
    op.drop_column("console_runtime_jobs", "workstream_id")
