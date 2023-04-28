from typing import List
from pydantic import BaseModel

class FilterBase(BaseModel):
    channel_id: int
    regex: str
    description: str

class FilterCreate(FilterBase):
    pass

class FilterUpdate(FilterBase):
    pass

class Filter(FilterBase):
    id: int

    class Config:
        orm_mode = True
