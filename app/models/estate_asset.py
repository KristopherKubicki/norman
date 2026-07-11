from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstateAsset(Base):
    __tablename__ = "estate_assets"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, ForeignKey("estate_principals.id"), nullable=False)
    place_id = Column(Integer, ForeignKey("estate_places.id"), nullable=True)
    worker_id = Column(Integer, ForeignKey("estate_workers.id"), nullable=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    control_class_id = Column(
        Integer, ForeignKey("estate_control_classes.id"), nullable=True
    )
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
