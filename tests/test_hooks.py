from fastapi.testclient import TestClient
from app.handlers import openai_handler
import app.app_routes as app_routes
from app.core import hooks
from app.core.config import settings


async def _dummy_chat_interaction(
    messages,
    max_tokens=openai_handler.DEFAULT_MAX_TOKENS,
    model=openai_handler.DEFAULT_MODEL,
):
    return {
        "model": model,
        "choices": [{"message": {"content": "assistant reply"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _pre_hook(message, context):
    return message + " pre", context


def _post_hook(reply, context):
    return reply + " post", context


def test_message_hooks(monkeypatch, test_app: TestClient):
    monkeypatch.setattr(
        openai_handler, "create_chat_interaction", _dummy_chat_interaction
    )
    monkeypatch.setattr(app_routes, "create_chat_interaction", _dummy_chat_interaction)

    hooks._pre_hooks.clear()
    hooks._post_hooks.clear()
    hooks.register_pre_hook(_pre_hook)
    hooks.register_post_hook(_post_hook)

    payload = {
        "name": "hookbot",
        "description": "desc",
        "gpt_model": settings.openai_default_model,
    }
    resp = test_app.post("/api/bots/create", json=payload)
    assert resp.status_code == 200
    bot_id = resp.json()["id"]

    resp = test_app.post(f"/api/bots/{bot_id}/messages", json={"content": "hello"})
    assert resp.status_code == 200

    resp = test_app.get(f"/api/bots/{bot_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert messages[0]["text"] == "hello pre"
    assert messages[1]["text"] == "assistant reply post"
