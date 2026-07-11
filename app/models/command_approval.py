from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db.base import Base


class CommandApproval(Base):
    __tablename__ = "command_approvals"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    connector_id = Column(
        Integer, ForeignKey("connectors.id"), index=True, nullable=False
    )
    event_id = Column(Integer, ForeignKey("routing_events.id"), index=True)

    command_text = Column(String, nullable=False)
    command_class = Column(String, nullable=False, default="change")
    status = Column(
        String, nullable=False, default="pending"
    )  # pending|approved|rejected|executed

    reason = Column(String)
    confirm_token = Column(String)

    created_at = Column(DateTime, default=func.now())
    decided_at = Column(DateTime)
