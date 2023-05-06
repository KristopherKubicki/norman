from typing import List, Optional
from pydantic import BaseModel

class BotBase(BaseModel):
    name: str
    session_id: str
    gpt_model: str

class BotCreate(BaseModel):
    name: str
    description: Optional[str] = None
    gpt_model: str

class BotOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    class Config:
        orm_mode = True

class BotUpdate(BotBase):
    pass

class Bot(BotBase):
    id: int

    class Config:
        orm_mode = True
