from sqlalchemy.orm import Session
from . import models

def get_bot_by_id(db: Session, bot_id: int):
    return db.query(models.Bot).filter(models.Bot.id == bot_id).first()

def create_bot(db: Session, bot: models.Bot):
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot
