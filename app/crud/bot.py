from sqlalchemy.orm import Session
from app import models, schemas

def get_bot_by_id(db: Session, bot_id: int):
    return db.query(models.Bot).filter(models.Bot.id == bot_id).first()

def create_bot(db: Session, bot_create: schemas.BotCreate):
    bot = models.Bot(name=bot_create.name, description=bot_create.description)
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot

def delete_bot(db: Session, bot_id: int):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if bot is None:
        return None
    db.delete(bot)
    db.commit()
    return bot

def update_bot(db: Session, bot_id: int, bot_data: schemas.BotUpdate):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if bot is None:
        return None
    for key, value in bot_data.dict().items():
        if value is not None:
            setattr(bot, key, value)
    db.commit()
    return bot
