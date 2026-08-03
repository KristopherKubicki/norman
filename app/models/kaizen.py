"""Durable records for the Norllama Kaizen control plane."""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class KaizenCandidateRecord(Base):
    """Reserve the candidate lifecycle storage for later Kaizen phases."""

    __tablename__ = "kaizen_candidates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    candidate_id = Column(String, nullable=False, unique=True, index=True)
    realm = Column(String, nullable=False, index=True)
    source_tui = Column(String, nullable=False, default="", index=True)
    lane = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False, index=True)
    target_ref = Column(String, nullable=False, default="")
    fingerprint = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="discovered", index=True)
    severity = Column(String, nullable=False, default="info", index=True)
    risk_tier = Column(String, nullable=False, default="read_only")
    impact_score = Column(Float, nullable=False, default=0.0)
    confidence_score = Column(Float, nullable=False, default=0.0)
    evidence_refs_json = Column(JSON, nullable=True)
    evidence_summary = Column(String, nullable=False, default="")
    proposal_json = Column(JSON, nullable=True)
    model_receipt_ref = Column(String, nullable=False, default="")
    expires_at = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class KaizenCandidateFingerprintRecord(Base):
    """Track durable candidate deduplication and operator suppression."""

    __tablename__ = "kaizen_candidate_fingerprints"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "realm",
            "target_type",
            "fingerprint",
            name="uq_kaizen_candidate_fingerprints_scope",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    realm = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False, index=True)
    fingerprint = Column(String, nullable=False, index=True)
    active_candidate_id = Column(String, nullable=False, default="", index=True)
    last_outcome = Column(String, nullable=False, default="")
    dismissal_reason = Column(String, nullable=False, default="")
    snoozed_until = Column(DateTime(timezone=True), index=True)
    cooldown_until = Column(DateTime(timezone=True), index=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class KaizenKpiObservationRecord(Base):
    """Store sanitized, deterministic KPI observations."""

    __tablename__ = "kaizen_kpi_observations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "realm",
            "source_tui",
            "kpi_id",
            "observed_at",
            name="uq_kaizen_kpi_observations_source_time",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    realm = Column(String, nullable=False, index=True)
    source_tui = Column(String, nullable=False, default="", index=True)
    kpi_id = Column(String, nullable=False, index=True)
    definition_version = Column(String, nullable=False, default="v1")
    source_type = Column(String, nullable=False, index=True)
    value_numeric = Column(Float, nullable=True)
    unit = Column(String, nullable=False, default="")
    state = Column(String, nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    window_start = Column(DateTime(timezone=True), nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=False, index=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    details_json = Column(JSON, nullable=True)
    evidence_refs_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class KaizenReportRecord(Base):
    """Persist API-only daily and weekly Kaizen reports."""

    __tablename__ = "kaizen_reports"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "realm",
            "kind",
            "period_key",
            name="uq_kaizen_reports_scope_period",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    realm = Column(String, nullable=False, index=True)
    report_id = Column(String, nullable=False, unique=True, index=True)
    kind = Column(String, nullable=False, index=True)
    period_key = Column(String, nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False, index=True)
    delivery_state = Column(String, nullable=False, default="api_only", index=True)
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class KaizenPolicyActionRecord(Base):
    """Audit bounded policy outcomes, including broker no-action decisions."""

    __tablename__ = "kaizen_policy_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    realm = Column(String, nullable=False, index=True)
    source_tui = Column(String, nullable=False, default="", index=True)
    action_id = Column(String, nullable=False, unique=True, index=True)
    policy_id = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False, default="", index=True)
    trigger_json = Column(JSON, nullable=True)
    bounds_json = Column(JSON, nullable=True)
    receipt_json = Column(JSON, nullable=True)
    verification_json = Column(JSON, nullable=True)
    rollback_json = Column(JSON, nullable=True)
    cooldown_until = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
