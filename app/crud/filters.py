from typing import Optional
from sqlalchemy.orm import Session

from app.models.channel_filter import Filter as FilterModel
from app.schemas.filter import FilterCreate, FilterUpdate


def create(db: Session, filter_create: FilterCreate) -> FilterModel:
    db_obj = FilterModel(**filter_create.dict())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get(db: Session, filter_id: int) -> Optional[FilterModel]:
    return db.query(FilterModel).filter(FilterModel.id == filter_id).first()


def update(db: Session, filter_id: int, filter_update: FilterUpdate) -> Optional[FilterModel]:
    db_obj = get(db, filter_id)
    if not db_obj:
        return None
    for field, value in filter_update.dict(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete(db: Session, filter_id: int) -> Optional[FilterModel]:
    db_obj = get(db, filter_id)
    if db_obj:
        db.delete(db_obj)
        db.commit()
    return db_obj
