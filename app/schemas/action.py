from typing import List
from pydantic import BaseModel, Field, conint

class ActionBase(BaseModel):
    channel_filter_id: conint(gt=0)
    prompt: str
    reply_channel_id: conint(gt=0) = Field(..., alias="reply_to")
    execution_order: conint(gt=0)

    class Config:
        allow_population_by_field_name = True

class ActionCreate(ActionBase):
    """Schema for creating an action."""

class ActionUpdate(ActionBase):
    """Schema for updating an action."""

class Action(ActionBase):
    id: int

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
