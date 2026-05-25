from typing import Optional

from pydantic import BaseModel, Field, constr


class ConsoleTargetBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    kind: constr(strip_whitespace=True, min_length=1) = Field(default="tmux")
    socket_path: Optional[str] = None
    session_name: Optional[str] = None
    target: constr(strip_whitespace=True, min_length=1)


class ConsoleTargetCreate(ConsoleTargetBase):
    """Schema for creating a console target (favorite)."""


class ConsoleTargetUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1)] = None
    socket_path: Optional[str] = None
    session_name: Optional[str] = None
    target: Optional[constr(strip_whitespace=True, min_length=1)] = None


class ConsoleTargetOut(ConsoleTargetBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True
