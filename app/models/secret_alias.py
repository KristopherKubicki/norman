from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
)
from sqlalchemy.sql import func

from app.db.base import Base


class SecretAlias(Base):
    __tablename__ = "secret_aliases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    provider_id = Column(
        Integer, ForeignKey("secret_providers.id"), nullable=False, index=True
    )
    backend_ref = Column(String, nullable=False)
    lane = Column(String, nullable=False, default="shared_infra", index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    default_ttl_seconds = Column(Integer, nullable=False, default=900)
    allow_raw_reveal = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
