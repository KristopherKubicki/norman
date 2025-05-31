from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.sql.schema import FetchedValue
from app.db.base import Base


class Message(Base):
    __tablename__ = "message"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    #user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source = Column(String, nullable=False, server_default='user')  # 'user', 'assistant', or 'system'
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)



