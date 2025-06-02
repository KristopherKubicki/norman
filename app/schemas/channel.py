from typing import List
from pydantic import BaseModel, constr, conint


class ChannelBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    connector_id: conint(gt=0)


class ChannelCreate(ChannelBase):
    pass


class ChannelUpdate(ChannelBase):
    pass


class Channel(ChannelBase):
    id: int

    class Config:
        orm_mode = True
