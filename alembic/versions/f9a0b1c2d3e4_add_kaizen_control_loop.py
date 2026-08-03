"""add observe-only Kaizen control loop storage

Revision ID: f9a0b1c2d3e4
Revises: e7f8a9b0c1d2
Create Date: 2026-08-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f9a0b1c2d3e4"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kaizen_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("realm", sa.String(), nullable=False),
        sa.Column("source_tui", sa.String(), nullable=False, server_default=""),
        sa.Column("lane", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_ref", sa.String(), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="discovered"),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"),
        sa.Column("risk_tier", sa.String(), nullable=False, server_default="read_only"),
        sa.Column("impact_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("evidence_summary", sa.String(), nullable=False, server_default=""),
        sa.Column("proposal_json", sa.JSON(), nullable=True),
        sa.Column("model_receipt_ref", sa.String(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("candidate_id", name="uq_kaizen_candidates_candidate_id"),
    )
    _create_indexes(
        "kaizen_candidates",
        [
            "id",
            "user_id",
            "candidate_id",
            "realm",
            "source_tui",
            "lane",
            "target_type",
            "fingerprint",
            "status",
            "severity",
            "expires_at",
            "created_at",
            "updated_at",
        ],
    )
    op.create_table(
        "kaizen_candidate_fingerprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("realm", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column(
            "active_candidate_id", sa.String(), nullable=False, server_default=""
        ),
        sa.Column("last_outcome", sa.String(), nullable=False, server_default=""),
        sa.Column("dismissal_reason", sa.String(), nullable=False, server_default=""),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id",
            "realm",
            "target_type",
            "fingerprint",
            name="uq_kaizen_candidate_fingerprints_scope",
        ),
    )
    _create_indexes(
        "kaizen_candidate_fingerprints",
        [
            "id",
            "user_id",
            "realm",
            "target_type",
            "fingerprint",
            "active_candidate_id",
            "snoozed_until",
            "cooldown_until",
            "created_at",
            "updated_at",
        ],
    )
    _create_observation_table()
    _create_report_table()
    _create_policy_action_table()


def _create_observation_table():
    op.create_table(
        "kaizen_kpi_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("realm", sa.String(), nullable=False),
        sa.Column("source_tui", sa.String(), nullable=False, server_default=""),
        sa.Column("kpi_id", sa.String(), nullable=False),
        sa.Column(
            "definition_version", sa.String(), nullable=False, server_default="v1"
        ),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(), nullable=False, server_default=""),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id",
            "realm",
            "source_tui",
            "kpi_id",
            "observed_at",
            name="uq_kaizen_kpi_observations_source_time",
        ),
    )
    _create_indexes(
        "kaizen_kpi_observations",
        [
            "id",
            "user_id",
            "realm",
            "source_tui",
            "kpi_id",
            "source_type",
            "state",
            "window_start",
            "window_end",
            "observed_at",
            "created_at",
        ],
    )


def _create_report_table():
    op.create_table(
        "kaizen_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("realm", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("period_key", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "delivery_state", sa.String(), nullable=False, server_default="api_only"
        ),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("report_id", name="uq_kaizen_reports_report_id"),
        sa.UniqueConstraint(
            "user_id",
            "realm",
            "kind",
            "period_key",
            name="uq_kaizen_reports_scope_period",
        ),
    )
    _create_indexes(
        "kaizen_reports",
        [
            "id",
            "user_id",
            "realm",
            "report_id",
            "kind",
            "period_key",
            "period_start",
            "period_end",
            "delivery_state",
            "created_at",
            "updated_at",
        ],
    )


def _create_policy_action_table():
    op.create_table(
        "kaizen_policy_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("realm", sa.String(), nullable=False),
        sa.Column("source_tui", sa.String(), nullable=False, server_default=""),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, server_default=""),
        sa.Column("trigger_json", sa.JSON(), nullable=True),
        sa.Column("bounds_json", sa.JSON(), nullable=True),
        sa.Column("receipt_json", sa.JSON(), nullable=True),
        sa.Column("verification_json", sa.JSON(), nullable=True),
        sa.Column("rollback_json", sa.JSON(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("action_id", name="uq_kaizen_policy_actions_action_id"),
    )
    _create_indexes(
        "kaizen_policy_actions",
        [
            "id",
            "user_id",
            "realm",
            "source_tui",
            "action_id",
            "policy_id",
            "state",
            "idempotency_key",
            "cooldown_until",
            "created_at",
            "updated_at",
        ],
    )


def _create_indexes(table_name, columns):
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def downgrade():
    _drop_table_with_indexes(
        "kaizen_policy_actions",
        [
            "updated_at",
            "created_at",
            "cooldown_until",
            "idempotency_key",
            "state",
            "policy_id",
            "action_id",
            "source_tui",
            "realm",
            "user_id",
            "id",
        ],
    )
    _drop_table_with_indexes(
        "kaizen_reports",
        [
            "updated_at",
            "created_at",
            "delivery_state",
            "period_end",
            "period_start",
            "period_key",
            "kind",
            "report_id",
            "realm",
            "user_id",
            "id",
        ],
    )
    _drop_table_with_indexes(
        "kaizen_kpi_observations",
        [
            "created_at",
            "observed_at",
            "window_end",
            "window_start",
            "state",
            "source_type",
            "kpi_id",
            "source_tui",
            "realm",
            "user_id",
            "id",
        ],
    )
    _drop_table_with_indexes(
        "kaizen_candidate_fingerprints",
        [
            "updated_at",
            "created_at",
            "cooldown_until",
            "snoozed_until",
            "active_candidate_id",
            "fingerprint",
            "target_type",
            "realm",
            "user_id",
            "id",
        ],
    )
    _drop_table_with_indexes(
        "kaizen_candidates",
        [
            "updated_at",
            "created_at",
            "expires_at",
            "severity",
            "status",
            "fingerprint",
            "target_type",
            "lane",
            "source_tui",
            "realm",
            "candidate_id",
            "user_id",
            "id",
        ],
    )


def _drop_table_with_indexes(table_name, columns):
    for column in columns:
        op.drop_index(f"ix_{table_name}_{column}", table_name=table_name)
    op.drop_table(table_name)
