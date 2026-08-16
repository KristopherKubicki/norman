from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class KeysCapabilityRequest(Base):
    __tablename__ = "keys_capability_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_uuid = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    host_enrollment_id = Column(
        Integer, ForeignKey("keys_host_enrollments.id"), nullable=False, index=True
    )
    capability_id = Column(
        Integer, ForeignKey("keys_capabilities.id"), nullable=False, index=True
    )
    policy_id = Column(
        Integer, ForeignKey("keys_capability_policies.id"), nullable=False, index=True
    )
    requester_type = Column(String, nullable=False, index=True)
    requester_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, default="", index=True)
    lane = Column(String, nullable=False, default="", index=True)
    action = Column(String, nullable=False, index=True)
    action_hash = Column(String, nullable=False)
    target_host = Column(String, nullable=False, default="", index=True)
    reason = Column(String, nullable=False, default="")
    requested_ttl_seconds = Column(Integer, nullable=False, default=900)
    status = Column(String, nullable=False, default="pending", index=True)
    approval_required = Column(Boolean, nullable=False, default=True)
    approval_reason = Column(String, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_at = Column(DateTime(timezone=True))
    decided_by = Column(Integer, ForeignKey("users.id"), index=True)
