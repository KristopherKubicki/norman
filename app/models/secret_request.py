from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class SecretRequest(Base):
    __tablename__ = "secret_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_uuid = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    requester_type = Column(String, nullable=False, default="agent", index=True)
    requester_id = Column(String, nullable=False, index=True)
    session_id = Column(String, index=True)
    secret_alias = Column(String, nullable=False, index=True)
    requested_mode = Column(String, nullable=False, default="inject")
    requested_ttl_seconds = Column(Integer, nullable=False, default=900)
    lane = Column(String, index=True)
    intent = Column(String)
    reason = Column(String)
    target_host = Column(String, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    policy_id = Column(Integer, ForeignKey("secret_policies.id"), index=True)
    approval_required = Column(Boolean, nullable=False, default=True)
    approval_reason = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_at = Column(DateTime(timezone=True))
    decided_by = Column(Integer, ForeignKey("users.id"), index=True)
