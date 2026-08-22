from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class BridgeConversationRecord(Base):
    __tablename__ = "bridge_conversations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "principal_slug",
            "direct_agent_slug",
            name="uq_bridge_conversations_direct_agent",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(String, nullable=False, unique=True, index=True)
    kind = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    principal_slug = Column(String, nullable=False, default="", index=True)
    domain_slug = Column(String, nullable=False, default="", index=True)
    direct_agent_slug = Column(String, index=True)
    member_slugs_json = Column(JSON, nullable=False, default=list)
    metadata_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
