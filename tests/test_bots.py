import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.bot import BotCreate
from app.core.config import settings
from app.tests.utils.utils import random_lower_string

def test_create_bot(test_app: TestClient, db: Session) -> None:
    gpt_model = settings.openai_default_model
    name = random_lower_string()
    session_id = "session123"
    bot_in = BotCreate(
        gpt_model=gpt_model, name=name, description="desc", session_id=session_id
    )
    bot = crud.create_bot(db, bot_create=bot_in)
    assert bot.gpt_model == gpt_model
    assert bot.name == name
    assert bot.session_id == session_id

def test_get_bot(test_app: TestClient, db: Session) -> None:
    gpt_model = settings.openai_default_model
    name = random_lower_string()
    session_id = "session123"
    bot_in = BotCreate(
        gpt_model=gpt_model, name=name, description="desc", session_id=session_id
    )
    bot = crud.create_bot(db, bot_create=bot_in)
    bot_2 = crud.get_bot_by_id(db, bot.id)
    assert bot_2
    assert bot.gpt_model == bot_2.gpt_model
    assert bot.name == bot_2.name
    assert bot.id == bot_2.id
    assert bot.session_id == bot_2.session_id

