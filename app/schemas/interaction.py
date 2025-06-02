from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime


class InteractionBase(BaseModel):
    message_id: int
    bot_id: int
    input_data: str
    output_data: str
    tokens_in: int
    gpt_model: str
    tokens_out: int
    status_code: int
    headers: str


class InteractionCreate(InteractionBase):
    pass


class InteractionUpdate(BaseModel):
    """Model for updating an existing interaction."""

    message_id: Optional[int] = None
    bot_id: Optional[int] = None
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    tokens_in: Optional[int] = None
    gpt_model: Optional[str] = None
    tokens_out: Optional[int] = None
    status_code: Optional[int] = None
    headers: Optional[str] = None


class Interaction(InteractionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
