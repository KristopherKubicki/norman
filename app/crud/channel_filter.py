from sqlalchemy.orm import Session
from . import models

def get_channel_filter_by_id(db: Session, channel_filter_id: int):
    return db.query(models.Filter).filter(models.Filter.id == channel_filter_id).first()

def create_channel_filter(db: Session, channel_filter: models.Filter):
    db.add(channel_filter)
    db.commit()
    db.refresh(channel_filter)
    return channel_filter
