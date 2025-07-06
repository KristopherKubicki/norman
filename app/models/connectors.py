from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from app.db.base import Base


class Connector(Base):
    __tablename__ = "connectors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    connector_type = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_message_sent = Column(DateTime(timezone=True))
    last_message_received = Column(DateTime(timezone=True))
    last_successful_message = Column(DateTime(timezone=True))
    config = Column(JSON)
