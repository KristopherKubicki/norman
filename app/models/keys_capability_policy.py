from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class KeysCapabilityPolicy(Base):
    __tablename__ = "keys_capability_policies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    capability_id = Column(
        Integer, ForeignKey("keys_capabilities.id"), nullable=False, index=True
    )
    requester_type = Column(String, nullable=False, default="agent", index=True)
    requester_id = Column(String, index=True)
    lane = Column(String, index=True)
    allowed_actions = Column(JSON, nullable=False, default=list)
    allowed_target_hosts = Column(JSON, nullable=False, default=list)
    max_ttl_seconds = Column(Integer, nullable=False, default=900)
    approval_required = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
