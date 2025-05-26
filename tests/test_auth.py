# tests/test_auth.py
import pytest

from app.schemas import Token


def test_authenticate_user(test_app):
    # Test invalid email or password
    response = test_app.post(
        "/token",
        data={"username": "invalid@example.com", "password": "invalid_password"},
    )
    assert response.status_code == 400

    # Test successful authentication
    response = test_app.post(
        "/token",
        data={"username": "test@example.com", "password": "test_password"},
    )
    assert response.status_code == 200
    token = response.json()
    assert "access_token" in token
    assert token["token_type"] == "bearer"


def test_protected_route(test_app):
    # Test access without a token
    response = test_app.get("/some_protected_route")
    assert response.status_code == 401

    # Test access with a valid token
    response = test_app.post(
        "/token",
        data={"username": "test@example.com", "password": "test_password"},
    )
    token = response.json()["access_token"]

    response = test_app.get(
        "/some_protected_route", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "message": "You have access to this protected route!",
        "user_email": "test@example.com",
    }

