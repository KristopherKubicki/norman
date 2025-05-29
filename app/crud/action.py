"""CRUD helpers for :class:`~app.models.action.Action`."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.action import Action as ActionModel
from app.schemas.action import ActionCreate, ActionUpdate


def get(db: Session, action_id: int) -> Optional[ActionModel]:
    """Return an action by its ID."""

    return db.query(ActionModel).filter(ActionModel.id == action_id).first()


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
