from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class SecretStashItem(Base):
    __tablename__ = "secret_stash_items"

    id = Column(Integer, primary_key=True, index=True)
    pointer_token = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), index=True)
    label = Column(String, nullable=False)
    encrypted_value = Column(Text, nullable=False)
    masked_preview = Column(String, nullable=False, default="")
    source = Column(String, nullable=False, default="manual", index=True)
    status = Column(String, nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_used_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    revoked_by = Column(Integer, ForeignKey("users.id"), index=True)

    @property
    def pointer_uri(self) -> str:
        return f"secret://stash/{self.pointer_token}"
