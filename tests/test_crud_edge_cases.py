import pytest
from sqlalchemy.orm import Session

from app import crud
from app.crud import message as message_crud
from app.schemas.bot import BotUpdate


def test_get_bot_invalid_id_returns_none(db: Session) -> None:
    assert crud.get_bot_by_id(db, 9999) is None


def test_delete_bot_invalid_id_returns_none(db: Session) -> None:
    assert crud.delete_bot(db, 9999) is None


def test_update_bot_invalid_id_returns_none(db: Session) -> None:
    update = BotUpdate(name="foo", gpt_model="gpt-4.1-mini")
    assert crud.update_bot(db, 9999, update) is None


def test_update_message_invalid_id_returns_none(db: Session) -> None:
    assert message_crud.update_message(db, 9999, "test") is None


def test_delete_message_invalid_id_no_error(db: Session) -> None:
    message_crud.delete_message(db, 9999)
