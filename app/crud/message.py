from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models import Message
from typing import List

def create_message(db: Session, bot_id: int, text: str, source: str) -> Message:
    db_message = Message(bot_id=bot_id, text=text, source=source)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_message_by_id(db: Session, message_id: int) -> Message:
    return db.query(Message).filter(Message.id == message_id).first()

def get_messages_by_bot_id(db: Session, bot_id: int) -> List[Message]:
    return db.query(Message).filter(Message.bot_id == bot_id).all()

def delete_message(db: Session, message_id: int) -> None:
    message = get_message_by_id(db, message_id)
    if message:
        db.delete(message)
        db.commit()

def update_message(db: Session, message_id: int, content: str) -> Message:
    message = get_message_by_id(db, message_id)
    if message:
        message.content = content
        db.commit()
        db.refresh(message)
        return message
    return None


def get_last_messages_by_bot_id(db: Session, bot_id: int, limit: int = 10):
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

