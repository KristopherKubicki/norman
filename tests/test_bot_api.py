from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models import Interaction, Message
from app import crud
from app.schemas.bot import BotCreate


def test_create_bot_api(test_app: TestClient, db: Session) -> None:
    payload = {"name": "test bot", "description": "desc", "gpt_model": "gpt-4.1-mini"}
    response = test_app.post("/api/bots/create", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]
    assert data["enabled"] is True
    assert "id" in data


def test_create_message_endpoint_stores_interaction(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    bot = crud.create_bot(
        db, BotCreate(name="bot", description="desc", gpt_model="gpt-4")
    )

    async def dummy_create_chat_interaction(*args, **kwargs):
        return {
            "model": "gpt-4",
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "headers": {},
        }

    monkeypatch.setattr(
        "app.app_routes.create_chat_interaction", dummy_create_chat_interaction
    )

    resp = test_app.post(f"/api/bots/{bot.id}/messages", json={"content": "hello"})
    assert resp.status_code == 200

    interaction = db.query(Interaction).filter(Interaction.bot_id == bot.id).first()
    assert interaction is not None
    user_message = (
        db.query(Message).filter(Message.id == interaction.message_id).first()
    )
    assert user_message is not None
    assert user_message.source == "user"
