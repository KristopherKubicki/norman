import pytest
import faulthandler
import time
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.handlers import openai_handler
import app.app_routes as app_routes
from app import crud
from app.core.security import create_access_token
from app.core.config import settings
from app.schemas.user import UserCreate
from app.tests.utils.utils import random_email, random_lower_string


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


def test_create_message_flow(monkeypatch, test_app: TestClient):
    monkeypatch.setattr(
        openai_handler, "create_chat_interaction", _dummy_chat_interaction
    )
    monkeypatch.setattr(app_routes, "create_chat_interaction", _dummy_chat_interaction)

    payload = {
        "name": "e2e bot",
        "description": "desc",
        "gpt_model": settings.openai_default_model,
    }
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

    # pagination with limit and cursor
    resp = test_app.get(f"/api/bots/{bot_id}/messages?limit=1")
    assert resp.status_code == 200
    first_page = resp.json()
    assert len(first_page) == 1
    cursor = first_page[0]["id"]

    resp = test_app.get(f"/api/bots/{bot_id}/messages?cursor={cursor}")
    assert resp.status_code == 200
    next_page = resp.json()
    assert len(next_page) == 1


def test_channels_flow(test_app: TestClient, db: Session):
    faulthandler.dump_traceback_later(20, repeat=True)
    email = random_email()
    password = "pass123"
    admin = UserCreate(email=email, username=random_lower_string(), password=password)
    user = crud.user.create_admin_user(
        db, email=admin.email, password=password, username=admin.username
    )
    db.close()

    token = create_access_token({"sub": user.email})
    headers = {"Authorization": f"Bearer {token}"}

    connector_payload = {
        "name": "e2e connector",
        "connector_type": "sample",
        "config": {},
    }
    print("create connector", flush=True)
    resp = test_app.post(
        "/api/connectors/create", json=connector_payload, headers=headers
    )
    if resp.status_code != 200:
        print("create connector response:", resp.status_code, resp.text, flush=True)
    assert resp.status_code == 200
    connector_id = resp.json()["id"]

    channel_payload = {"name": "e2e channel", "connector_id": connector_id}
    print("create channel", flush=True)
    resp = test_app.post("/api/v1/channels/", json=channel_payload, headers=headers)
    assert resp.status_code == 201
    channel = resp.json()
    channel_id = channel["id"]

    print("update channel", flush=True)
    resp = test_app.put(
        f"/api/v1/channels/{channel_id}",
        json={"name": "e2e channel updated", "connector_id": connector_id},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "e2e channel updated"

    print("post channel message", flush=True)
    resp = test_app.post(
        f"/api/v1/channels/{channel_id}/messages",
        json={"content": "hello channel"},
        headers=headers,
    )
    assert resp.status_code == 200
    message = resp.json()
    assert message["content"] == "hello channel"

    print("get channel messages", flush=True)
    resp = test_app.get(f"/api/v1/channels/{channel_id}/messages", headers=headers)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) >= 1

    print("delete channel", flush=True)
    resp = test_app.delete(f"/api/v1/channels/{channel_id}", headers=headers)
    if resp.status_code == 409:
        print("delete channel force", flush=True)
        resp = test_app.delete(
            f"/api/v1/channels/{channel_id}?force=true", headers=headers
        )
        assert resp.status_code == 200
    else:
        assert resp.status_code == 200
    faulthandler.cancel_dump_traceback_later()
