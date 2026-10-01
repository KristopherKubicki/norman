from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class KeysCapability(Base):
    """A server-side executor binding, never a client-delivered secret."""

    __tablename__ = "keys_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    executor_kind = Column(String, nullable=False, default="receipt")
    executor_ref = Column(String, nullable=False, default="")
    secret_aliases = Column(JSON, nullable=False, default=list)
    metadata_json = Column(JSON)
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
