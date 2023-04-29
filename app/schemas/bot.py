from typing import List, Optional
from pydantic import BaseModel

class BotBase(BaseModel):
    name: str
    gpt_model: str
    session_id: str

class BotCreate(BaseModel):
    name: str
    description: Optional[str] = None

class BotUpdate(BotBase):
    pass

class Bot(BotBase):
    id: int

    class Config:
        orm_mode = True
