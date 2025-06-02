from typing import List, Optional
from pydantic import BaseModel, constr


class BotBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    gpt_model: constr(strip_whitespace=True, min_length=1)
    session_id: Optional[str] = None


class BotCreate(BotBase):
    description: Optional[str] = None


class BotOut(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        orm_mode = True


class BotUpdate(BaseModel):
    """Model for updating existing bots."""

    name: Optional[constr(strip_whitespace=True, min_length=1)] = None
    gpt_model: Optional[constr(strip_whitespace=True, min_length=1)] = None
    session_id: Optional[str] = None
    description: Optional[str] = None


class Bot(BotBase):
    id: int

    class Config:
        orm_mode = True
