from sqlalchemy.orm import Session
from typing import Optional

from app import models, schemas

def get_bot_by_id(db: Session, bot_id: int) -> Optional[models.Bot]:
    return db.query(models.Bot).filter(models.Bot.id == bot_id).first()

def create_bot(db: Session, bot_create: schemas.BotCreate) -> models.Bot:
    bot = models.Bot(
        name=bot_create.name,
        description=bot_create.description,
        gpt_model=bot_create.gpt_model,
        session_id=bot_create.session_id,
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot

def delete_bot(db: Session, bot_id: int) -> Optional[models.Bot]:
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if bot is None:
        return None
    db.delete(bot)
    db.commit()
    return bot

def update_bot(db: Session, bot_id: int, bot_data: schemas.BotUpdate) -> Optional[models.Bot]:
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if bot is None:
        return None
    for key, value in bot_data.dict().items():
        if value is not None:
            setattr(bot, key, value)
    db.commit()
    return bot

