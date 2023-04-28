from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_channel():
    response = client.post("/channels/", json={"name": "test_channel", "connector": "irc", "details": {}})
    assert response.status_code == 201
    assert response.json()["name"] == "test_channel"
    assert response.json()["connector"] == "irc"
    assert "id" in response.json()

def test_get_channel():
    channel_id = 1  # Use an existing channel's ID
    response = client.get(f"/channels/{channel_id}")
    assert response.status_code == 200
    assert response.json()["id"] == channel_id
    assert response.json()["name"] == "test_channel"
    assert response.json()["connector"] == "irc"

# Add more tests for other routers and endpoints

