from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import Base


class ConsoleTarget(Base):
    __tablename__ = "console_targets"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_console_target_user_name"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)

    # Human-friendly label used across devices (phone/desktop).
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, server_default="tmux", index=True)

    # tmux-specific fields (kind=tmux)
    socket_path = Column(String, nullable=True)
    session_name = Column(String, nullable=True, index=True)
    target = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
