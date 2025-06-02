import pytest
from fastapi.testclient import TestClient

from app.handlers import openai_handler
import app.app_routes as app_routes


async def _dummy_chat_interaction(messages, max_tokens=openai_handler.DEFAULT_MAX_TOKENS, model=openai_handler.DEFAULT_MODEL):
    return {
        "model": model,
        "choices": [{"message": {"content": "assistant reply"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def test_create_message_flow(monkeypatch, test_app: TestClient):
    monkeypatch.setattr(openai_handler, "create_chat_interaction", _dummy_chat_interaction)
    monkeypatch.setattr(app_routes, "create_chat_interaction", _dummy_chat_interaction)

    payload = {"name": "e2e bot", "description": "desc", "gpt_model": "gpt-4.1-mini"}
    resp = test_app.post("/api/bots/create", json=payload)
    assert resp.status_code == 200
    bot_id = resp.json()["id"]

    resp = test_app.post(f"/api/bots/{bot_id}/messages", json={"content": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"

    resp = test_app.get(f"/api/bots/{bot_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    assert messages[0]["text"] == "hello"
    assert messages[1]["text"] == "assistant reply"
