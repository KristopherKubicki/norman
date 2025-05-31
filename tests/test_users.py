from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.crud.user import create_user, get_user_by_id
from app.schemas.user import UserCreate
from app.tests.utils.utils import random_email, random_lower_string


def test_create_and_get_user(test_app: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user = create_user(db, UserCreate(username=random_lower_string(), email=email, password=password))
    fetched = get_user_by_id(db, user.id)
    assert fetched.email == email
