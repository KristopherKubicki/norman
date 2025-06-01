"""CRUD operations for :class:`~app.models.channel.Channel`."""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.channel import Channel as ChannelModel
from app.schemas.channel import ChannelCreate, ChannelUpdate


def get(db: Session, channel_id: int) -> Optional[ChannelModel]:
    """Return a channel by its ID."""
    return db.query(ChannelModel).filter(ChannelModel.id == channel_id).first()


def get_multi(db: Session, skip: int = 0, limit: int = 100) -> List[ChannelModel]:
    """Return multiple channels."""
    return db.query(ChannelModel).offset(skip).limit(limit).all()


def create(db: Session, obj_in: ChannelCreate) -> ChannelModel:
    """Create a new channel."""
    db_obj = ChannelModel(name=obj_in.name, connector_id=obj_in.connector_id)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(db: Session, db_obj: ChannelModel, obj_in: ChannelUpdate) -> ChannelModel:
    """Update an existing channel."""
    for field, value in obj_in.dict(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def remove(db: Session, channel_id: int) -> Optional[ChannelModel]:
    """Delete a channel and return the deleted instance."""
    obj = get(db, channel_id)
    if obj:
        db.delete(obj)
        db.commit()
    return obj

