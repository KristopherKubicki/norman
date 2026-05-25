from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class SecretPolicy(Base):
    __tablename__ = "secret_policies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    requester_type = Column(String, nullable=False, default="agent", index=True)
    requester_id = Column(String, index=True)
    lane = Column(String, index=True)
    secret_prefix = Column(String, nullable=False, index=True)
    allowed_modes = Column(JSON, nullable=False, default=list)
    max_ttl_seconds = Column(Integer, nullable=False, default=900)
    approval_required = Column(Boolean, nullable=False, default=True)
    raw_reveal_allowed = Column(Boolean, nullable=False, default=False)
    allowed_hosts = Column(JSON)
    reuse_window_seconds = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
