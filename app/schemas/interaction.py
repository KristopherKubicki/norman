from typing import List
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


class InteractionUpdate(InteractionBase):
    pass


class Interaction(InteractionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
