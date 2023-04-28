from typing import List
from pydantic import BaseModel

class ChannelFilterBase(BaseModel):
    channel_id: int
    regex: str
    description: str

class ChannelFilterCreate(ChannelFilterBase):
    pass

class ChannelFilterUpdate(ChannelFilterBase):
    pass

class ChannelFilter(ChannelFilterBase):
    id: int

    class Config:
        orm_mode = True
