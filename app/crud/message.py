from sqlalchemy.orm import Session
from app.models import Message
from typing import List

def create_message(db: Session, bot_id: int, text: str) -> Message:
    db_message = Message(bot_id=bot_id, text=text)
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

