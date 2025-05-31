from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, String
from sqlalchemy.sql import func
from app.db.base import Base

class Interaction(Base):
    __tablename__ = "interactions"
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id"))
    input_data = Column(Text, nullable=False)
    output_data = Column(Text, nullable=False)
    tokens_in = Column(Integer, nullable=False)
    tokens_out = Column(Integer, nullable=False)
    gpt_model = Column(String, nullable=False)
    status_code = Column(Integer, nullable=True)
    headers = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
