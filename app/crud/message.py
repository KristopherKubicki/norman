from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
import logging

from app.models import Message

logger = logging.getLogger(__name__)

def create_message(db: Session, bot_id: int, text: str, source: str) -> Message:
    db_message = Message(bot_id=bot_id, text=text, source=source)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_message_by_id(db: Session, message_id: int) -> Optional[Message]:
    return db.query(Message).filter(Message.id == message_id).first()

def get_messages_by_bot_id(
    db: Session,
    bot_id: int,
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    cursor: Optional[int] = None,
) -> List[Message]:
    """Return messages for a bot with optional pagination."""

    query = db.query(Message).filter(Message.bot_id == bot_id).order_by(Message.created_at)
    if cursor is not None:
        query = query.filter(Message.id > cursor)
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()

def delete_message(db: Session, message_id: int) -> None:
    message = get_message_by_id(db, message_id)
    if message:
        db.delete(message)
        db.commit()
    else:
        logger.warning("Message id %s not found for deletion", message_id)

def update_message(db: Session, message_id: int, text: str) -> Optional[Message]:
    message = get_message_by_id(db, message_id)
    if message:
        message.text = text
        db.commit()
        db.refresh(message)
        return message
    logger.warning("Message id %s not found for update", message_id)
    return None


def get_last_messages_by_bot_id(db: Session, bot_id: int, limit: int = 10) -> List[Message]:
    return (
        db.query(Message)
        .filter(Message.bot_id == bot_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
        .all()
    )

def delete_messages_by_bot_id(db: Session, bot_id: int):
    db.query(Message).filter(Message.bot_id == bot_id).delete(synchronize_session='fetch')
    db.commit()

