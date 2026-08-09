import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, conint, constr, field_validator


class FilterBase(BaseModel):
    channel_id: conint(gt=0)
    regex: constr(strip_whitespace=True, min_length=1)
    description: str

    @field_validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError("Invalid regular expression") from exc
        return v


class FilterCreate(FilterBase):
    """Schema for creating a channel filter."""


class FilterUpdate(BaseModel):
    """Model for updating a filter."""

    channel_id: Optional[conint(gt=0)] = None
    regex: Optional[constr(strip_whitespace=True, min_length=1)] = None
    description: Optional[str] = None


class Filter(FilterBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
