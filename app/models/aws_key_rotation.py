"""Durable, encrypted rotation state; never exposed through raw-secret APIs."""

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class AWSKeyRotation(Base):
    """One fixed-account rotation, with atomic state transitions."""

    __tablename__ = "aws_key_rotations"

    account_id = Column(String(12), primary_key=True)
    rotation_id = Column(String(36), nullable=False, unique=True)
    old_key_id = Column(String(128), nullable=False)
    new_key_id = Column(String(128), nullable=True)
    encrypted_credential = Column(Text, nullable=True)
    state = Column(String(32), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
