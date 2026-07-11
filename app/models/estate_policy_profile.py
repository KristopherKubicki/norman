from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstatePolicyProfile(Base):
    __tablename__ = "estate_policy_profiles"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    requires_approval = Column(Boolean, nullable=False, default=False)
    allows_outbound_send = Column(Boolean, nullable=False, default=False)
    allows_runtime_control = Column(Boolean, nullable=False, default=False)
    allows_side_effects = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
