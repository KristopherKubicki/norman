from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstateDomain(Base):
    __tablename__ = "estate_domains"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, ForeignKey("estate_principals.id"), nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    default_policy_profile_id = Column(
        Integer, ForeignKey("estate_policy_profiles.id"), nullable=True
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
