from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate
from app.tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session):
    email = random_email()
    password = "pass123"
    user_in = UserCreate(email=email, username=random_lower_string(), password=password)
    user = crud.user.create_user(db, user=user_in)
    return user, password


def test_frontend_script_included(test_app: TestClient, db: Session) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={"username": user.email, "password": password},
        allow_redirects=False,
    )
    token = resp.cookies.get("access_token").strip('"')
    resp2 = test_app.get("/index.html", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert "frontend/main.js" in resp2.text
