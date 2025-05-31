"""CRUD tests for the Bot helpers."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.bot import BotCreate
from app.tests.utils.utils import random_lower_string

def test_create_bot(test_app: TestClient, db: Session) -> None:
    gpt_model = "gpt-4"
    name = random_lower_string()
    bot_in = BotCreate(gpt_model=gpt_model, name=name, description="desc")
    bot = crud.bot.create_bot(db, bot_create=bot_in)
    assert bot.gpt_model == gpt_model
    assert bot.name == name

def test_get_bot(test_app: TestClient, db: Session) -> None:
    gpt_model = "gpt-4"
    name = random_lower_string()
    bot_in = BotCreate(gpt_model=gpt_model, name=name, description="desc")
    bot = crud.bot.create_bot(db, bot_create=bot_in)
    bot_2 = crud.bot.get_bot_by_id(db, bot.id)
    assert bot_2
    assert bot.gpt_model == bot_2.gpt_model
    assert bot.name == bot_2.name
    assert bot.id == bot_2.id
