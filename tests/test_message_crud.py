from sqlalchemy.orm import Session

from app.crud import message as message_crud
from app.models import Message


def test_update_message(db: Session) -> None:
    # create message
    msg = message_crud.create_message(db, bot_id=1, text="hello", source="user")
    # update message text
    updated = message_crud.update_message(db, msg.id, "goodbye")
    assert isinstance(updated, Message)
    assert updated.text == "goodbye"
