from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class ConsoleRuntimeJobRecord(Base):
    __tablename__ = "console_runtime_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    objective = Column(String, nullable=False)
    contract_json = Column(JSON, nullable=False)
    metadata_json = Column(JSON)
    workstream_id = Column(String, index=True)
    parent_job_id = Column(String, index=True)
    result_json = Column(JSON)
    cancel_requested_at = Column(DateTime(timezone=True), index=True)
    lease_json = Column(JSON)
    lease_epoch = Column(Integer, nullable=False, default=0)
    checkpoints_json = Column(JSON)
    checkpoint_capsules_json = Column(JSON)
    artifacts_json = Column(JSON)
    artifact_records_json = Column(JSON)
    verification_receipts_json = Column(JSON)
    last_error = Column(String, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConsoleRuntimeWorkstreamRecord(Base):
    __tablename__ = "console_runtime_workstreams"
    __table_args__ = (
        UniqueConstraint(
            "coordinator_job_id",
            name="uq_console_runtime_workstreams_coordinator_job",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    workstream_id = Column(String, nullable=False, unique=True, index=True)
    coordinator_job_id = Column(
        String,
        ForeignKey("console_runtime_jobs.job_id"),
        nullable=False,
        index=True,
    )
    title = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="active", index=True)
    metadata_json = Column(JSON)
    max_concurrency = Column(Integer, nullable=False, default=10)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConsoleRuntimeJobDependencyRecord(Base):
    __tablename__ = "console_runtime_job_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "depends_on_job_id",
            name="uq_console_runtime_job_dependencies_pair",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    workstream_id = Column(
        String,
        ForeignKey("console_runtime_workstreams.workstream_id"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        String,
        ForeignKey("console_runtime_jobs.job_id"),
        nullable=False,
        index=True,
    )
    depends_on_job_id = Column(
        String,
        ForeignKey("console_runtime_jobs.job_id"),
        nullable=False,
        index=True,
    )
    artifact_requirements_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConsoleRuntimeEffectRecord(Base):
    __tablename__ = "console_runtime_effects"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "effect_key",
            name="uq_console_runtime_effects_job_effect_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(
        String,
        ForeignKey("console_runtime_jobs.job_id"),
        nullable=False,
        index=True,
    )
    effect_key = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False, default="planned", index=True)
    attempt_id = Column(String, nullable=False, default="", index=True)
    lease_epoch = Column(Integer, nullable=False, default=0)
    approval_ref = Column(String, nullable=False, default="")
    preconditions_json = Column(JSON)
    receipt_json = Column(JSON)
    artifact_refs_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConsoleRuntimeEventRecord(Base):
    __tablename__ = "console_runtime_events"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_console_runtime_events_job_sequence",
        ),
        UniqueConstraint(
            "event_id",
            name="uq_console_runtime_events_event_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(
        String,
        ForeignKey("console_runtime_jobs.job_id"),
        nullable=False,
        index=True,
    )
    event_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    summary = Column(String, nullable=False, default="")
    detail = Column(String, nullable=False, default="")
    visibility = Column(String, nullable=False, default="timeline", index=True)
    payload_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
