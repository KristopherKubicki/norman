from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class SecretAuditEvent(Base):
    __tablename__ = "secret_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    request_id = Column(Integer, ForeignKey("secret_requests.id"), index=True)
    lease_id = Column(Integer, ForeignKey("secret_leases.id"), index=True)
    event_type = Column(String, nullable=False, index=True)
    actor_type = Column(String, nullable=False, default="system")
    actor_id = Column(String)
    summary = Column(String, nullable=False)
    metadata_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
