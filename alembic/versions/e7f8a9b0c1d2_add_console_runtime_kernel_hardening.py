"""add console runtime kernel hardening

Revision ID: e7f8a9b0c1d2
Revises: d8e4f5a6b7c8
Create Date: 2026-08-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c1d2"
down_revision = "d8e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "console_runtime_jobs",
        sa.Column("lease_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("checkpoint_capsules_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("artifact_records_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "console_runtime_jobs",
        sa.Column("verification_receipts_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "console_runtime_job_dependencies",
        sa.Column("artifact_requirements_json", sa.JSON(), nullable=True),
    )
    op.create_table(
        "console_runtime_effects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("console_runtime_jobs.job_id"),
            nullable=False,
        ),
        sa.Column("effect_key", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="planned"),
        sa.Column("attempt_id", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approval_ref", sa.String(), nullable=False, server_default=""),
        sa.Column("preconditions_json", sa.JSON(), nullable=True),
        sa.Column("receipt_json", sa.JSON(), nullable=True),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "job_id",
            "effect_key",
            name="uq_console_runtime_effects_job_effect_key",
        ),
    )
    op.create_index(
        "ix_console_runtime_effects_id", "console_runtime_effects", ["id"]
    )
    op.create_index(
        "ix_console_runtime_effects_user_id",
        "console_runtime_effects",
        ["user_id"],
    )
    op.create_index(
        "ix_console_runtime_effects_job_id", "console_runtime_effects", ["job_id"]
    )
    op.create_index(
        "ix_console_runtime_effects_effect_key",
        "console_runtime_effects",
        ["effect_key"],
    )
    op.create_index(
        "ix_console_runtime_effects_kind", "console_runtime_effects", ["kind"]
    )
    op.create_index(
        "ix_console_runtime_effects_state", "console_runtime_effects", ["state"]
    )
    op.create_index(
        "ix_console_runtime_effects_attempt_id",
        "console_runtime_effects",
        ["attempt_id"],
    )
    op.create_index(
        "ix_console_runtime_effects_created_at",
        "console_runtime_effects",
        ["created_at"],
    )
    op.create_index(
        "ix_console_runtime_effects_updated_at",
        "console_runtime_effects",
        ["updated_at"],
    )


def downgrade():
    op.drop_index(
        "ix_console_runtime_effects_updated_at", table_name="console_runtime_effects"
    )
    op.drop_index(
        "ix_console_runtime_effects_created_at", table_name="console_runtime_effects"
    )
    op.drop_index(
        "ix_console_runtime_effects_attempt_id", table_name="console_runtime_effects"
    )
    op.drop_index("ix_console_runtime_effects_state", table_name="console_runtime_effects")
    op.drop_index("ix_console_runtime_effects_kind", table_name="console_runtime_effects")
    op.drop_index(
        "ix_console_runtime_effects_effect_key", table_name="console_runtime_effects"
    )
    op.drop_index(
        "ix_console_runtime_effects_job_id", table_name="console_runtime_effects"
    )
    op.drop_index(
        "ix_console_runtime_effects_user_id", table_name="console_runtime_effects"
    )
    op.drop_index("ix_console_runtime_effects_id", table_name="console_runtime_effects")
    op.drop_table("console_runtime_effects")
    op.drop_column("console_runtime_job_dependencies", "artifact_requirements_json")
    op.drop_column("console_runtime_jobs", "verification_receipts_json")
    op.drop_column("console_runtime_jobs", "artifact_records_json")
    op.drop_column("console_runtime_jobs", "checkpoint_capsules_json")
    op.drop_column("console_runtime_jobs", "lease_epoch")
