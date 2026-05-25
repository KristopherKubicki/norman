"""add norman keys tables

Revision ID: f3e5c4a1b2d0
Revises: 6b0f56df66f1
Create Date: 2026-03-28 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f3e5c4a1b2d0"
down_revision = "6b0f56df66f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_secret_providers_id", "secret_providers", ["id"])
    op.create_index("ix_secret_providers_kind", "secret_providers", ["kind"])
    op.create_index("ix_secret_providers_name", "secret_providers", ["name"], unique=True)

    op.create_table(
        "secret_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("secret_providers.id"), nullable=False),
        sa.Column("backend_ref", sa.String(), nullable=False),
        sa.Column("lane", sa.String(), nullable=False, server_default="shared_infra"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("allow_raw_reveal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_secret_aliases_id", "secret_aliases", ["id"])
    op.create_index("ix_secret_aliases_name", "secret_aliases", ["name"], unique=True)
    op.create_index("ix_secret_aliases_provider_id", "secret_aliases", ["provider_id"])
    op.create_index("ix_secret_aliases_lane", "secret_aliases", ["lane"])

    op.create_table(
        "secret_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("requester_type", sa.String(), nullable=False, server_default="agent"),
        sa.Column("requester_id", sa.String(), nullable=True),
        sa.Column("lane", sa.String(), nullable=True),
        sa.Column("secret_prefix", sa.String(), nullable=False),
        sa.Column("allowed_modes", sa.JSON(), nullable=False),
        sa.Column("max_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("raw_reveal_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_hosts", sa.JSON(), nullable=True),
        sa.Column("reuse_window_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_secret_policies_id", "secret_policies", ["id"])
    op.create_index("ix_secret_policies_name", "secret_policies", ["name"], unique=True)
    op.create_index("ix_secret_policies_requester_type", "secret_policies", ["requester_type"])
    op.create_index("ix_secret_policies_requester_id", "secret_policies", ["requester_id"])
    op.create_index("ix_secret_policies_lane", "secret_policies", ["lane"])
    op.create_index("ix_secret_policies_secret_prefix", "secret_policies", ["secret_prefix"])

    op.create_table(
        "secret_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_uuid", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requester_type", sa.String(), nullable=False, server_default="agent"),
        sa.Column("requester_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("secret_alias", sa.String(), nullable=False),
        sa.Column("requested_mode", sa.String(), nullable=False, server_default="inject"),
        sa.Column("requested_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("lane", sa.String(), nullable=True),
        sa.Column("intent", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("target_host", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("secret_policies.id"), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approval_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_secret_requests_id", "secret_requests", ["id"])
    op.create_index("ix_secret_requests_request_uuid", "secret_requests", ["request_uuid"], unique=True)
    op.create_index("ix_secret_requests_user_id", "secret_requests", ["user_id"])
    op.create_index("ix_secret_requests_requester_type", "secret_requests", ["requester_type"])
    op.create_index("ix_secret_requests_requester_id", "secret_requests", ["requester_id"])
    op.create_index("ix_secret_requests_session_id", "secret_requests", ["session_id"])
    op.create_index("ix_secret_requests_secret_alias", "secret_requests", ["secret_alias"])
    op.create_index("ix_secret_requests_lane", "secret_requests", ["lane"])
    op.create_index("ix_secret_requests_target_host", "secret_requests", ["target_host"])
    op.create_index("ix_secret_requests_status", "secret_requests", ["status"])
    op.create_index("ix_secret_requests_policy_id", "secret_requests", ["policy_id"])
    op.create_index("ix_secret_requests_decided_by", "secret_requests", ["decided_by"])

    op.create_table(
        "secret_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_uuid", sa.String(), nullable=False),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("secret_requests.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("secret_providers.id"), nullable=False),
        sa.Column("provider_lease_id", sa.String(), nullable=True),
        sa.Column("secret_alias", sa.String(), nullable=False),
        sa.Column("granted_mode", sa.String(), nullable=False, server_default="inject"),
        sa.Column("granted_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("renewable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("issued_to", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_secret_leases_id", "secret_leases", ["id"])
    op.create_index("ix_secret_leases_lease_uuid", "secret_leases", ["lease_uuid"], unique=True)
    op.create_index("ix_secret_leases_request_id", "secret_leases", ["request_id"])
    op.create_index("ix_secret_leases_provider_id", "secret_leases", ["provider_id"])
    op.create_index("ix_secret_leases_provider_lease_id", "secret_leases", ["provider_lease_id"])
    op.create_index("ix_secret_leases_secret_alias", "secret_leases", ["secret_alias"])
    op.create_index("ix_secret_leases_status", "secret_leases", ["status"])
    op.create_index("ix_secret_leases_issued_to", "secret_leases", ["issued_to"])
    op.create_index("ix_secret_leases_expires_at", "secret_leases", ["expires_at"])
    op.create_index("ix_secret_leases_revoked_by", "secret_leases", ["revoked_by"])

    op.create_table(
        "secret_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("secret_requests.id"), nullable=True),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("secret_leases.id"), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_secret_audit_events_id", "secret_audit_events", ["id"])
    op.create_index("ix_secret_audit_events_user_id", "secret_audit_events", ["user_id"])
    op.create_index("ix_secret_audit_events_request_id", "secret_audit_events", ["request_id"])
    op.create_index("ix_secret_audit_events_lease_id", "secret_audit_events", ["lease_id"])
    op.create_index("ix_secret_audit_events_event_type", "secret_audit_events", ["event_type"])


def downgrade():
    op.drop_index("ix_secret_audit_events_event_type", table_name="secret_audit_events")
    op.drop_index("ix_secret_audit_events_lease_id", table_name="secret_audit_events")
    op.drop_index("ix_secret_audit_events_request_id", table_name="secret_audit_events")
    op.drop_index("ix_secret_audit_events_user_id", table_name="secret_audit_events")
    op.drop_index("ix_secret_audit_events_id", table_name="secret_audit_events")
    op.drop_table("secret_audit_events")

    op.drop_index("ix_secret_leases_revoked_by", table_name="secret_leases")
    op.drop_index("ix_secret_leases_expires_at", table_name="secret_leases")
    op.drop_index("ix_secret_leases_issued_to", table_name="secret_leases")
    op.drop_index("ix_secret_leases_status", table_name="secret_leases")
    op.drop_index("ix_secret_leases_secret_alias", table_name="secret_leases")
    op.drop_index("ix_secret_leases_provider_lease_id", table_name="secret_leases")
    op.drop_index("ix_secret_leases_provider_id", table_name="secret_leases")
    op.drop_index("ix_secret_leases_request_id", table_name="secret_leases")
    op.drop_index("ix_secret_leases_lease_uuid", table_name="secret_leases")
    op.drop_index("ix_secret_leases_id", table_name="secret_leases")
    op.drop_table("secret_leases")

    op.drop_index("ix_secret_requests_decided_by", table_name="secret_requests")
    op.drop_index("ix_secret_requests_policy_id", table_name="secret_requests")
    op.drop_index("ix_secret_requests_status", table_name="secret_requests")
    op.drop_index("ix_secret_requests_target_host", table_name="secret_requests")
    op.drop_index("ix_secret_requests_lane", table_name="secret_requests")
    op.drop_index("ix_secret_requests_secret_alias", table_name="secret_requests")
    op.drop_index("ix_secret_requests_session_id", table_name="secret_requests")
    op.drop_index("ix_secret_requests_requester_id", table_name="secret_requests")
    op.drop_index("ix_secret_requests_requester_type", table_name="secret_requests")
    op.drop_index("ix_secret_requests_user_id", table_name="secret_requests")
    op.drop_index("ix_secret_requests_request_uuid", table_name="secret_requests")
    op.drop_index("ix_secret_requests_id", table_name="secret_requests")
    op.drop_table("secret_requests")

    op.drop_index("ix_secret_policies_secret_prefix", table_name="secret_policies")
    op.drop_index("ix_secret_policies_lane", table_name="secret_policies")
    op.drop_index("ix_secret_policies_requester_id", table_name="secret_policies")
    op.drop_index("ix_secret_policies_requester_type", table_name="secret_policies")
    op.drop_index("ix_secret_policies_name", table_name="secret_policies")
    op.drop_index("ix_secret_policies_id", table_name="secret_policies")
    op.drop_table("secret_policies")

    op.drop_index("ix_secret_aliases_lane", table_name="secret_aliases")
    op.drop_index("ix_secret_aliases_provider_id", table_name="secret_aliases")
    op.drop_index("ix_secret_aliases_name", table_name="secret_aliases")
    op.drop_index("ix_secret_aliases_id", table_name="secret_aliases")
    op.drop_table("secret_aliases")

    op.drop_index("ix_secret_providers_name", table_name="secret_providers")
    op.drop_index("ix_secret_providers_kind", table_name="secret_providers")
    op.drop_index("ix_secret_providers_id", table_name="secret_providers")
    op.drop_table("secret_providers")
