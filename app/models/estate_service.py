from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class EstateService(Base):
    __tablename__ = "estate_services"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, ForeignKey("estate_principals.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("estate_domains.id"), nullable=False)
    bot_id = Column(Integer, ForeignKey("estate_bots.id"), nullable=True)
    worker_id = Column(Integer, ForeignKey("estate_workers.id"), nullable=True)
    place_id = Column(Integer, ForeignKey("estate_places.id"), nullable=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    policy_profile_id = Column(
        Integer, ForeignKey("estate_policy_profiles.id"), nullable=True
    )
    web_url = Column(String, nullable=True)
    web_url_tailnet = Column(String, nullable=True)
    console_url = Column(String, nullable=True)
    console_url_tailnet = Column(String, nullable=True)
    start_command = Column(Text, nullable=True)
    healthcheck = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
