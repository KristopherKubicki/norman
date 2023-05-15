from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class MessageBase(BaseModel):
    text: str

class MessageCreate(MessageBase):
    pass


class MessageUpdate(MessageBase):
    pass


class MessageInDBBase(MessageBase):
    id: int
    bot_id: int
    created_at: datetime
    source: str

    class Config:
        orm_mode = True


class Message(MessageInDBBase):
    pass


class MessageInDB(MessageInDBBase):
    pass

