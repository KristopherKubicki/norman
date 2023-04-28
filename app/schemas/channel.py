from typing import List
from pydantic import BaseModel

class ChannelBase(BaseModel):
    name: str
    connector_id: int

class ChannelCreate(ChannelBase):
    pass

class ChannelUpdate(ChannelBase):
    pass

class Channel(ChannelBase):
    id: int

    class Config:
        orm_mode = True
