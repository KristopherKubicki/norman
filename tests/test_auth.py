# tests/test_auth.py
"""Authentication flow tests."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.core.security import create_access_token
from app.schemas.user import UserCreate, UserAuthenticate
from app.tests.utils.utils import random_email, random_lower_string


def test_authenticate_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(username=random_lower_string(), email=email, password=password)
    crud.user.create_user(db, user=user_in)

    assert crud.user.authenticate_user(db, UserAuthenticate(email=email, password="wrong")) is None

    user = crud.user.authenticate_user(db, UserAuthenticate(email=email, password=password))
    assert user is not None


def test_protected_route(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(username=random_lower_string(), email=email, password=password)
    crud.user.create_user(db, user=user_in)

    response = test_app.get("/bots.html", follow_redirects=False)
    assert response.status_code == 303

