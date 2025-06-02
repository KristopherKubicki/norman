from typing import List
from pydantic import BaseModel, Field

class ActionBase(BaseModel):
    channel_filter_id: int
    prompt: str
    reply_channel_id: int = Field(..., alias="reply_to")
    execution_order: int

    class Config:
        allow_population_by_field_name = True

class ActionCreate(ActionBase):
    pass

class ActionUpdate(ActionBase):
    pass

class Action(ActionBase):
    id: int

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
