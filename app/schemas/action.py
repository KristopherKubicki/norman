from typing import List
from pydantic import BaseModel

class ActionBase(BaseModel):
    channel_filter_id: int
    prompt: str
    reply_channel_id: int
    execution_order: int

class ActionCreate(ActionBase):
    pass

class ActionUpdate(ActionBase):
    pass

class Action(ActionBase):
    id: int

    class Config:
        orm_mode = True
