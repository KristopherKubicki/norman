"""Basic integration tests for the FastAPI application."""

import json

from fastapi.testclient import TestClient


def test_homepage_returns_html(test_app: TestClient) -> None:
    """The root endpoint should return the index page."""
    response = test_app.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_get_bot_messages_empty(test_app: TestClient) -> None:
    """The messages endpoint should return an empty list for a new bot."""
    payload = {"name": "test bot", "description": "desc", "gpt_model": "gpt-4"}
    create = test_app.post("/api/bots/create", json=payload)
    assert create.status_code == 200
    bot_id = create.json()["id"]

    response = test_app.get(f"/api/bots/{bot_id}/messages")
    assert response.status_code == 200
    assert json.loads(response.text) == []
