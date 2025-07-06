from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class MessageBase(BaseModel):
    text: str


class MessageCreate(MessageBase):
    """Schema for creating a message."""


class MessageUpdate(BaseModel):
    """Model for updating a message."""

    text: Optional[str] = None


class MessageInDBBase(MessageBase):
    id: int
    bot_id: int
    created_at: datetime
    source: str

    class Config:
        orm_mode = True


class Message(MessageInDBBase):
    """Public message model."""


class MessageInDB(MessageInDBBase):
    """Internal message model with DB specifics."""
