from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.connectors import Connector as ConnectorModel
from app.schemas.connector import ConnectorCreate, ConnectorUpdate


def get(db: Session, connector_id: int) -> Optional[ConnectorModel]:
    """Return a connector by its ID."""
    return db.query(ConnectorModel).filter(ConnectorModel.id == connector_id).first()


def get_multi(db: Session, skip: int = 0, limit: int = 100) -> List[ConnectorModel]:
    """Return multiple connectors with optional pagination."""
    return db.query(ConnectorModel).offset(skip).limit(limit).all()


def create(db: Session, obj_in: ConnectorCreate) -> ConnectorModel:
    """Create a new connector."""
    db_obj = ConnectorModel(**obj_in.dict())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(
    db: Session, db_obj: ConnectorModel, obj_in: ConnectorUpdate
) -> ConnectorModel:
    """Update an existing connector."""
    for field, value in obj_in.dict(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def remove(db: Session, connector_id: int) -> Optional[ConnectorModel]:
    """Delete a connector and return the deleted instance."""
    obj = get(db, connector_id)
    if obj:
        db.delete(obj)
        db.commit()
    return obj
