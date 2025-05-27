import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app

client = TestClient(app)


def test_channel_crud(db: Session):
    # Create channel
    response = client.post("/api/v1/channels/", json={"name": "test", "connector_id": 1})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test"
    channel_id = data["id"]

    # Get channel
    response = client.get(f"/api/v1/channels/{channel_id}")
    assert response.status_code == 200
    assert response.json()["id"] == channel_id

    # Update channel
    response = client.put(f"/api/v1/channels/{channel_id}", json={"name": "updated", "connector_id": 1})
    assert response.status_code == 200
    assert response.json()["name"] == "updated"

    # List channels
    response = client.get("/api/v1/channels/")
    assert response.status_code == 200
    assert any(ch["id"] == channel_id for ch in response.json())

    # Delete channel
    response = client.delete(f"/api/v1/channels/{channel_id}")
    assert response.status_code == 200
    assert response.json()["id"] == channel_id

    # Verify deletion
    response = client.get(f"/api/v1/channels/{channel_id}")
    assert response.status_code == 404
