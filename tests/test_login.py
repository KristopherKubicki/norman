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
        follow_redirects=False,
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
        follow_redirects=False,
    )
    assert resp.status_code == 303
    token = resp.cookies.get("access_token").strip('"')
    resp2 = test_app.get(
        "/", headers={"Authorization": f"Bearer {token}"}, follow_redirects=False
    )
    assert resp2.status_code == 200
    assert 'id="norman-bridge"' in resp2.text


def test_login_uses_bridge_language(test_app: TestClient) -> None:
    response = test_app.get("/login.html")
    assert response.status_code == 200
    assert "Log in to Norman" in response.text
    assert "Enter Norman" not in response.text


def test_login_returns_to_requested_bridge_path(
    test_app: TestClient, db: Session
) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={
            "username": user.email,
            "password": password,
            "next": "/bridge?agent=housebot",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/bridge?agent=housebot"
