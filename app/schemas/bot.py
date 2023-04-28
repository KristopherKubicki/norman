from typing import List
from pydantic import BaseModel

class BotBase(BaseModel):
    name: str
    gpt_model: str
    session_id: str

class BotCreate(BotBase):
    pass

class BotUpdate(BotBase):
    pass

class Bot(BotBase):
    id: int

    class Config:
        orm_mode = True
