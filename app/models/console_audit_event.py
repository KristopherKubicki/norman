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


class ConsoleAuditEvent(Base):
    __tablename__ = "console_audit_events"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "source_event_id",
            name="uq_console_audit_events_connector_source_event",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connector_id = Column(
        Integer, ForeignKey("connectors.id"), nullable=False, index=True
    )
    connector_name = Column(String, nullable=False, server_default="")
    session_name = Column(String, nullable=False, server_default="", index=True)
    agent_name = Column(String, nullable=False, server_default="", index=True)
    host_name = Column(String, nullable=False, server_default="", index=True)
    source_event_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, server_default="info", index=True)
    actor_type = Column(String, nullable=False, server_default="system")
    actor_ip = Column(String)
    thread_id = Column(String, index=True)
    summary = Column(String, nullable=False)
    detail = Column(String)
    payload_json = Column(JSON)
    event_at = Column(DateTime(timezone=True), nullable=False, index=True)
    collected_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
