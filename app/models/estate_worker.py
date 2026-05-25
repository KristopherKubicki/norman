from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstateWorker(Base):
    __tablename__ = "estate_workers"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, ForeignKey("estate_principals.id"), nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    hostname = Column(String, nullable=True)
    place_id = Column(Integer, ForeignKey("estate_places.id"), nullable=True)
    control_class_id = Column(
        Integer, ForeignKey("estate_control_classes.id"), nullable=True
    )
    policy_profile_id = Column(
        Integer, ForeignKey("estate_policy_profiles.id"), nullable=True
    )
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
