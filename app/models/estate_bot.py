from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstateBot(Base):
    __tablename__ = "estate_bots"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, ForeignKey("estate_principals.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("estate_domains.id"), nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    class_name = Column(String, nullable=False)
    policy_profile_id = Column(
        Integer, ForeignKey("estate_policy_profiles.id"), nullable=False
    )
    owner_person_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
