# app/schemas/user.py

from pydantic import ConfigDict, BaseModel, EmailStr
from typing import Optional


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(UserBase):
    email: Optional[EmailStr] = None
    password: Optional[str] = None


class User(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class UserAuthenticate(BaseModel):
    email: EmailStr
    password: str

    model_config = ConfigDict(from_attributes=True)
