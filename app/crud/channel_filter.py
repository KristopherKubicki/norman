from typing import Optional
from sqlalchemy.orm import Session

from app import models
from app.models.channel import Channel as ChannelModel
from app.models.connectors import Connector as ConnectorModel
from app.schemas.filter import FilterCreate, FilterUpdate


def get(db: Session, filter_id: int) -> Optional[models.Filter]:
    return db.query(models.Filter).filter(models.Filter.id == filter_id).first()


def get_for_user(db: Session, filter_id: int, user_id: int) -> Optional[models.Filter]:
    return (
        db.query(models.Filter)
        .join(ChannelModel, models.Filter.channel_id == ChannelModel.id)
        .join(ConnectorModel, ChannelModel.connector_id == ConnectorModel.id)
        .filter(models.Filter.id == filter_id, ConnectorModel.user_id == user_id)
        .first()
    )


def get_multi_by_user(db: Session, user_id: int):
    return (
        db.query(models.Filter)
        .join(ChannelModel, models.Filter.channel_id == ChannelModel.id)
        .join(ConnectorModel, ChannelModel.connector_id == ConnectorModel.id)
        .filter(ConnectorModel.user_id == user_id)
        .all()
    )


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


def update(
    db: Session, filter_id: int, obj_in: FilterUpdate
) -> Optional[models.Filter]:
    filter_ = get(db, filter_id)
    if filter_ is None:
        return None
    for key, value in obj_in.dict(exclude_unset=True).items():
        setattr(filter_, key, value)
    db.commit()
    db.refresh(filter_)
    return filter_


def delete_by_channel(db: Session, channel_id: int) -> int:
    deleted = (
        db.query(models.Filter)
        .filter(models.Filter.channel_id == channel_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
