from typing import List, Optional
from pydantic import BaseModel, constr, conint, validator
import re


class FilterBase(BaseModel):
    channel_id: conint(gt=0)
    regex: constr(strip_whitespace=True, min_length=1)
    description: str

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError("Invalid regular expression") from exc
        return v


class FilterCreate(FilterBase):
    pass


class FilterUpdate(BaseModel):
    """Model for updating a filter."""

    channel_id: Optional[conint(gt=0)] = None
    regex: Optional[constr(strip_whitespace=True, min_length=1)] = None
    description: Optional[str] = None


class Filter(FilterBase):
    id: int

    class Config:
        orm_mode = True
