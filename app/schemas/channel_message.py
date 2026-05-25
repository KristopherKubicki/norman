from datetime import datetime
from pydantic import BaseModel, constr


class ChannelMessageBase(BaseModel):
    content: constr(strip_whitespace=True, min_length=1)


class ChannelMessageCreate(ChannelMessageBase):
    """Schema for creating a channel message."""


class ChannelMessageOut(ChannelMessageBase):
    id: int
    channel_id: int
    source: str
    created_at: datetime

    class Config:
        orm_mode = True
