# tests/api_v1/test_users.py

from fastapi.testclient import TestClient
from app.main import app
from app.schemas.user import UserCreate

client = TestClient(app)

def test_create_user():
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpassword",
    }
    response = client.post("/api/v1/users/", json=user_data)
    assert response.status_code == 200

    created_user = response.json()
    assert created_user["username"] == user_data["username"]
    assert created_user["email"] == user_data["email"]
    assert "password" not in created_user
    assert "id" in created_user
