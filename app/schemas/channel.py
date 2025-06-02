from typing import List, Optional
from pydantic import BaseModel, constr, conint


class ChannelBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    connector_id: conint(gt=0)


class ChannelCreate(ChannelBase):
    pass


class ChannelUpdate(BaseModel):
    """Model for updating an existing channel."""

    name: Optional[constr(strip_whitespace=True, min_length=1)] = None
    connector_id: Optional[conint(gt=0)] = None


class Channel(ChannelBase):
    id: int

    class Config:
        orm_mode = True
