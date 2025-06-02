from typing import Optional, List
from sqlalchemy.orm import Session

from app.models.channel_filter import Filter as FilterModel
from app.schemas.filter import FilterCreate, FilterUpdate


def create(db: Session, filter_create: FilterCreate) -> FilterModel:
    """Create a new channel filter."""
    db_obj = FilterModel(**filter_create.dict())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get(db: Session, filter_id: int) -> Optional[FilterModel]:
    """Return a filter by its ID."""
    return db.query(FilterModel).filter(FilterModel.id == filter_id).first()


def get_multi(db: Session, skip: int = 0, limit: int = 100) -> List[FilterModel]:
    """Return multiple filters."""
    return db.query(FilterModel).offset(skip).limit(limit).all()


def update(db: Session, filter_id: int, filter_update: FilterUpdate) -> Optional[FilterModel]:
    """Update an existing filter."""
    db_obj = get(db, filter_id)
    if not db_obj:
        return None
    for field, value in filter_update.dict(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete(db: Session, filter_id: int) -> Optional[FilterModel]:
    """Delete a filter and return the deleted instance."""
    db_obj = get(db, filter_id)
    if db_obj:
        db.delete(db_obj)
        db.commit()
    return db_obj


def remove(db: Session, filter_id: int) -> Optional[FilterModel]:
    """Alias for delete to maintain API consistency."""
    return delete(db, filter_id)
