from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.sql import func
from app.db.base import Base


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    connector_id = Column(Integer, ForeignKey("connectors.id"), index=True)
    connector_type = Column(String, index=True)
    destination_connector_id = Column(Integer, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), index=True, nullable=False)
    match_type = Column(String, nullable=False, default="all")
    match_value = Column(String)
    priority = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class RoutingEvent(Base):
    __tablename__ = "routing_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    connector_id = Column(Integer, ForeignKey("connectors.id"), index=True)
    connector_type = Column(String, index=True)
    destination_connector_id = Column(Integer, index=True)
    destination_connector_type = Column(String)
    bot_id = Column(Integer, ForeignKey("bots.id"), index=True)
    rule_id = Column(Integer, ForeignKey("routing_rules.id"), index=True)
    message_text = Column(String)
    payload = Column(JSON)
    status = Column(String, nullable=False, default="received")
    delivery_status = Column(String, nullable=False, default="skipped")
    error = Column(String)
    delivery_error = Column(String)
    idempotency_key = Column(String, index=True, unique=True)
    created_at = Column(DateTime, default=func.now())


class RoutingJob(Base):
    __tablename__ = "routing_jobs"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("routing_events.id"), index=True)
    connector_id = Column(Integer, ForeignKey("connectors.id"), index=True)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime, nullable=False, default=func.now())
    last_error = Column(String)
    payload = Column(JSON)
    normalized = Column(JSON)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
