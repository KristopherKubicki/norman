from typing import Optional
from typing import List
from sqlalchemy.orm import Session

from app import models
from app.schemas.filter import FilterCreate, FilterUpdate

def get(db: Session, filter_id: int) -> Optional[models.Filter]:
    return db.query(models.Filter).filter(models.Filter.id == filter_id).first()

def create(db: Session, obj_in: FilterCreate) -> models.Filter:
    filter_ = models.Filter(**obj_in.dict())
    db.add(filter_)
    db.commit()
    db.refresh(filter_)
    return filter_

def delete(db: Session, filter_id: int) -> Optional[models.Filter]:
    filter_ = get(db, filter_id)
    if filter_ is not None:
        db.delete(filter_)
        db.commit()
    return filter_

def update(db: Session, filter_id: int, obj_in: FilterUpdate) -> Optional[models.Filter]:
    filter_ = get(db, filter_id)
    if filter_ is None:
        return None
    for key, value in obj_in.dict(exclude_unset=True).items():
        setattr(filter_, key, value)
    db.commit()
    db.refresh(filter_)
    return filter_


def get_filters_for_channel(db: Session, channel_id: int) -> List[models.Filter]:
    """Return all filters associated with ``channel_id``."""
    return (
        db.query(models.Filter)
        .filter(models.Filter.channel_id == channel_id)
        .all()
    )

