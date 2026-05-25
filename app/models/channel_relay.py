from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class ChannelRelay(Base):
    __tablename__ = "channel_relays"

    id = Column(Integer, primary_key=True, index=True)
    relay_id = Column(String, nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    source_message_id = Column(
        Integer, ForeignKey("channel_messages.id"), nullable=False, index=True
    )
    source_connector_id = Column(Integer, ForeignKey("connectors.id"), index=True)
    target_connector_id = Column(Integer, ForeignKey("connectors.id"), index=True)
    target_name = Column(String, nullable=False, default="")
    callback_url = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="created", index=True)
    success = Column(Boolean)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=False, default="")
    summary = Column(String, nullable=False, default="")
    thread_id = Column(String, nullable=False, default="")
    payload = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), index=True)
    accepted_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    stale_at = Column(DateTime(timezone=True))
