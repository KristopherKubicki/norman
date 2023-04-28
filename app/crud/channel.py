from sqlalchemy.orm import Session
from . import models

def get_channel_by_id(db: Session, channel_id: int):
    return db.query(models.Channel).filter(models.Channel.id == channel_id).first()

def create_channel(db: Session, channel: models.Channel):
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel
