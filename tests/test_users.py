import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate
from app.tests.utils.utils import random_email, random_lower_string

def test_create_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()
    user_in = UserCreate(email=email, password=password, username=username)
    user = crud.user.create_user(db, user=user_in)
    assert user.email == email

def test_get_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()
    user_in = UserCreate(email=email, password=password, username=username)
    user = crud.user.create_user(db, user=user_in)
    user_2 = crud.user.get_user_by_id(db, user.id)
    assert user_2
    assert user.email == user_2.email
    assert user.id == user_2.id
