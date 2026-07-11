from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models import Interaction, Message
from app import crud
from app.schemas.bot import BotCreate
from app.core.config import settings
from app.schemas.user import UserCreate


def test_create_bot_api(test_app: TestClient, db: Session) -> None:
    payload = {
        "name": "test bot",
        "description": "desc",
        "gpt_model": settings.openai_default_model,
    }
    response = test_app.post("/api/bots/create", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]
    assert "id" in data


def test_create_message_endpoint_stores_interaction(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    bot = crud.create_bot(
        db,
        BotCreate(
            name="bot", description="desc", gpt_model=settings.openai_default_model
        ),
        user_id=user.id,
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
