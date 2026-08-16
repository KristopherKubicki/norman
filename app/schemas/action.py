from typing import List
from pydantic import ConfigDict, BaseModel, Field, conint


class ActionBase(BaseModel):
    channel_filter_id: conint(gt=0)
    prompt: str
    reply_channel_id: conint(gt=0) = Field(..., alias="reply_to")
    execution_order: conint(gt=0)

    model_config = ConfigDict(validate_by_name=True)


class ActionCreate(ActionBase):
    """Schema for creating an action."""


class ActionUpdate(ActionBase):
    """Schema for updating an action."""


class Action(ActionBase):
    id: int

    model_config = ConfigDict(from_attributes=True, validate_by_name=True)
