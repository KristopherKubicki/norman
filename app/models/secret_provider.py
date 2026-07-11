from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class SecretProvider(Base):
    __tablename__ = "secret_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    kind = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    config = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
