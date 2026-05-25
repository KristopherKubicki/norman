"""CRUD helpers for :class:`~app.models.action.Action`."""

from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.action import Action as ActionModel
from app.models.channel_filter import Filter as FilterModel
from app.models.channel import Channel as ChannelModel
from app.models.connectors import Connector as ConnectorModel
from app.schemas.action import ActionCreate, ActionUpdate


def get(db: Session, action_id: int) -> Optional[ActionModel]:
    """Return an action by its ID."""

    return db.query(ActionModel).filter(ActionModel.id == action_id).first()


def get_for_user(db: Session, action_id: int, user_id: int) -> Optional[ActionModel]:
    """Return an action if it belongs to the user via filter/channel."""
    return (
        db.query(ActionModel)
        .join(FilterModel, ActionModel.channel_filter_id == FilterModel.id)
        .join(ChannelModel, FilterModel.channel_id == ChannelModel.id)
        .join(ConnectorModel, ChannelModel.connector_id == ConnectorModel.id)
        .filter(ActionModel.id == action_id, ConnectorModel.user_id == user_id)
        .first()
    )


def get_multi_by_user(db: Session, user_id: int) -> List[ActionModel]:
    """Return all actions for a user via filter/channel ownership."""
    return (
        db.query(ActionModel)
        .join(FilterModel, ActionModel.channel_filter_id == FilterModel.id)
        .join(ChannelModel, FilterModel.channel_id == ChannelModel.id)
        .join(ConnectorModel, ChannelModel.connector_id == ConnectorModel.id)
        .filter(ConnectorModel.user_id == user_id)
        .order_by(ActionModel.execution_order.asc(), ActionModel.id.asc())
        .all()
    )


def create(db: Session, obj_in: ActionCreate) -> ActionModel:
    """Create a new action."""

    db_obj = ActionModel(
        channel_filter_id=obj_in.channel_filter_id,
        prompt=obj_in.prompt,
        reply_to=obj_in.reply_channel_id,
        execution_order=obj_in.execution_order,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(db: Session, db_obj: ActionModel, obj_in: ActionUpdate) -> ActionModel:
    """Update an existing action."""

    update_data = obj_in.dict(exclude_unset=True)
    if "reply_channel_id" in update_data:
        db_obj.reply_to = update_data.pop("reply_channel_id")
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def remove(db: Session, action_id: int) -> Optional[ActionModel]:
    """Delete an action and return the deleted instance."""

    obj = get(db, action_id)
    if obj:
        db.delete(obj)
        db.commit()
    return obj
