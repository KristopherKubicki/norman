from typing import Optional
from pydantic import BaseModel, constr, validator
from app.core.config import settings


class BotBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    gpt_model: constr(strip_whitespace=True, min_length=1)
    session_id: Optional[str] = None

    @validator("gpt_model")
    def validate_gpt_model(cls, v: str) -> str:
        if v not in settings.openai_available_models:
            raise ValueError(f"Invalid GPT model: {v}")
        return v


class BotCreate(BotBase):
    description: Optional[str] = None


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
