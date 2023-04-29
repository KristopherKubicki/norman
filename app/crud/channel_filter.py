from sqlalchemy.orm import Session
from . import models

def get_channel_filter_by_id(db: Session, channel_filter_id: int):
    return db.query(models.Filter).filter(models.Filter.id == channel_filter_id).first()

def create_filter(db: Session, filter_data: schemas.FilterCreate):
    filter_ = models.Filter(**filter_data.dict())
    db.add(filter_)
    db.commit()
    db.refresh(filter_)
    return filter_

def delete_filter(db: Session, filter_id: int):
    filter_ = db.query(models.Filter).filter(models.Filter.id == filter_id).first()
    if filter_ is not None:
        db.delete(filter_)
        db.commit()

def update_filter(db: Session, filter_id: int, filter_data: schemas.FilterUpdate):
    filter_ = db.query(models.Filter).filter(models.Filter.id == filter_id).first()
    if filter_ is None:
        return None
    for key, value in filter_data.dict().items():
        if value is not None:
            setattr(filter_, key, value)
    db.commit()
    return filter_

