from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_create_bot_api(test_app: TestClient, db: Session) -> None:
    payload = {"name": "test bot", "description": "desc", "gpt_model": "gpt-4.1-mini"}
    response = test_app.post("/api/bots/create", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]
    assert "id" in data
