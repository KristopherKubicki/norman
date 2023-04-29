from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from .base import Base

class Action(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True)
    channel_filter_id = Column(Integer, ForeignKey("channel_filters.id"))
    prompt = Column(Text, nullable=False)
    reply_to = Column(Integer, ForeignKey("channels.id"))
    execution_order = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
