import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate
from app.core.security import decode_access_token
from app.tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session):
    email = random_email()
    password = "pass123"
    user_in = UserCreate(email=email, username=random_lower_string(), password=password)
    user = crud.user.create_user(db, user=user_in)
    return user, password


def test_login_sets_cookie(test_app: TestClient, db: Session) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={"username": user.email, "password": password},
        allow_redirects=False,
    )
    assert resp.status_code == 303
    token = resp.cookies.get("access_token")
    assert token
    token = token.strip('"')
    assert decode_access_token(token) == user.email


def test_login_allows_access_to_home(test_app: TestClient, db: Session) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={"username": user.email, "password": password},
        allow_redirects=False,
    )
    assert resp.status_code == 303
    cookies = resp.cookies
    token = resp.cookies.get("access_token").strip('"')
    resp2 = test_app.get("/", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
