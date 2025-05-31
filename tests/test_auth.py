# tests/test_auth.py
from app.crud.user import create_user, authenticate_user
from app.schemas import Token
from app.schemas.user import UserCreate, UserAuthenticate
from app.tests.utils.utils import random_email, random_lower_string
from app.core.security import create_access_token


def test_authenticate_user(db):
    email = random_email()
    password = random_lower_string()
    create_user(db, UserCreate(username=random_lower_string(), email=email, password=password))

    user = authenticate_user(db, UserAuthenticate(email=email, password=password))
    assert user is not None

    bad = authenticate_user(db, UserAuthenticate(email=email, password="wrong"))
    assert bad is None



