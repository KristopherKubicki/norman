import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate, UserUpdate
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


def test_update_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()
    user_in = UserCreate(email=email, password=password, username=username)
    user = crud.user.create_user(db, user=user_in)
    new_username = random_lower_string()
    update_in = UserUpdate(username=new_username, email=email)
    updated = crud.user.update_user(db, user_id=user.id, user_data=update_in)
    assert updated.username == new_username


def test_delete_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()
    user_in = UserCreate(email=email, password=password, username=username)
    user = crud.user.create_user(db, user=user_in)
    deleted = crud.user.delete_user(db, user_id=user.id)
    assert deleted.id == user.id
    assert crud.user.get_user_by_id(db, user.id) is None
