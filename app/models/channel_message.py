from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    content = Column(String, nullable=False)
    source = Column(String, nullable=False, server_default="user")
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
