"""add enrolled host capability delivery for Norman Keys

Revision ID: c8d7e6f5a4b3
Revises: b7c4a9d2e6f1, f9a0b1c2d3e4
Create Date: 2026-08-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c8d7e6f5a4b3"
down_revision = ("b7c4a9d2e6f1", "f9a0b1c2d3e4")
branch_labels = None
depends_on = None


def _index(table: str, *names: str) -> None:
    for name in names:
        op.create_index(f"ix_{table}_{name}", table, [name])


def upgrade():
    op.create_table(
        "keys_host_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host_id", sa.String(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=False),
        sa.Column("identity_fingerprint", sa.String(), nullable=False),
        sa.Column("requester_ids", sa.JSON(), nullable=False),
        sa.Column("capability_names", sa.JSON(), nullable=False),
        sa.Column("lanes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.String(), nullable=False, server_default=""),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("host_id"),
        sa.UniqueConstraint("hostname"),
    )
    _index("keys_host_enrollments", "id", "host_id", "hostname", "status")

    op.create_table(
        "keys_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "executor_kind", sa.String(), nullable=False, server_default="receipt"
        ),
        sa.Column("executor_ref", sa.String(), nullable=False, server_default=""),
        sa.Column("secret_aliases", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name"),
    )
    _index("keys_capabilities", "id", "name")

    op.create_table(
        "keys_capability_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "capability_id",
            sa.Integer(),
            sa.ForeignKey("keys_capabilities.id"),
            nullable=False,
        ),
        sa.Column(
            "requester_type", sa.String(), nullable=False, server_default="agent"
        ),
        sa.Column("requester_id", sa.String(), nullable=True),
        sa.Column("lane", sa.String(), nullable=True),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("allowed_target_hosts", sa.JSON(), nullable=False),
        sa.Column(
            "max_ttl_seconds", sa.Integer(), nullable=False, server_default="900"
        ),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name"),
    )
    _index(
        "keys_capability_policies",
        "id",
        "capability_id",
        "requester_type",
        "requester_id",
        "lane",
    )

    op.create_table(
        "keys_capability_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_uuid", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "host_enrollment_id",
            sa.Integer(),
            sa.ForeignKey("keys_host_enrollments.id"),
            nullable=False,
        ),
        sa.Column(
            "capability_id",
            sa.Integer(),
            sa.ForeignKey("keys_capabilities.id"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("keys_capability_policies.id"),
            nullable=False,
        ),
        sa.Column("requester_type", sa.String(), nullable=False),
        sa.Column("requester_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False, server_default=""),
        sa.Column("lane", sa.String(), nullable=False, server_default=""),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("action_hash", sa.String(), nullable=False),
        sa.Column("target_host", sa.String(), nullable=False, server_default=""),
        sa.Column("reason", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "requested_ttl_seconds", sa.Integer(), nullable=False, server_default="900"
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("approval_reason", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("request_uuid"),
    )
    _index(
        "keys_capability_requests",
        "id",
        "request_uuid",
        "user_id",
        "host_enrollment_id",
        "capability_id",
        "policy_id",
        "requester_type",
        "requester_id",
        "session_id",
        "lane",
        "action",
        "target_host",
        "status",
        "decided_by",
    )

    op.create_table(
        "keys_capability_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_uuid", sa.String(), nullable=False),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("keys_capability_requests.id"),
            nullable=False,
        ),
        sa.Column(
            "capability_id",
            sa.Integer(),
            sa.ForeignKey("keys_capabilities.id"),
            nullable=False,
        ),
        sa.Column(
            "host_enrollment_id",
            sa.Integer(),
            sa.ForeignKey("keys_host_enrollments.id"),
            nullable=False,
        ),
        sa.Column("action_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("single_use", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invocation_receipt_uuid", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("lease_uuid"),
        sa.UniqueConstraint("invocation_receipt_uuid"),
    )
    _index(
        "keys_capability_leases",
        "id",
        "lease_uuid",
        "request_id",
        "capability_id",
        "host_enrollment_id",
        "status",
        "expires_at",
        "invocation_receipt_uuid",
        "revoked_by",
    )

    op.create_table(
        "keys_capability_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("keys_capability_requests.id"),
            nullable=True,
        ),
        sa.Column(
            "lease_id",
            sa.Integer(),
            sa.ForeignKey("keys_capability_leases.id"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(), nullable=False, server_default=""),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    _index("keys_capability_audit_events", "id", "request_id", "lease_id", "event_type")


def downgrade():
    for table, names in (
        (
            "keys_capability_audit_events",
            ("event_type", "lease_id", "request_id", "id"),
        ),
        (
            "keys_capability_leases",
            (
                "revoked_by",
                "invocation_receipt_uuid",
                "expires_at",
                "status",
                "host_enrollment_id",
                "capability_id",
                "request_id",
                "lease_uuid",
                "id",
            ),
        ),
        (
            "keys_capability_requests",
            (
                "decided_by",
                "status",
                "target_host",
                "action",
                "lane",
                "session_id",
                "requester_id",
                "requester_type",
                "policy_id",
                "capability_id",
                "host_enrollment_id",
                "user_id",
                "request_uuid",
                "id",
            ),
        ),
        (
            "keys_capability_policies",
            ("lane", "requester_id", "requester_type", "capability_id", "id"),
        ),
        ("keys_capabilities", ("name", "id")),
        ("keys_host_enrollments", ("status", "hostname", "host_id", "id")),
    ):
        for name in names:
            op.drop_index(f"ix_{table}_{name}", table_name=table)
        op.drop_table(table)
