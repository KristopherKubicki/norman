from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base

class Bot(Base):
    __tablename__ = "bots"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    session_id = Column(String, nullable=True)
    gpt_model = Column(String, nullable=False, default="gpt-4")
    system_prompt = Column(String, nullable=False, default="You are a helpful assistant.")
    default_response_tokens = Column(Integer, nullable=False, default=150) # how much to generate
    default_prompt_tokens = Column(Integer, nullable=False, default=1000) # how many messages back
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


