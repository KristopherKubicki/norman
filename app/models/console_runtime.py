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
    lease_json = Column(JSON)
    checkpoints_json = Column(JSON)
    artifacts_json = Column(JSON)
    last_error = Column(String, nullable=False, default="")
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
