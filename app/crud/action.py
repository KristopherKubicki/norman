from sqlalchemy.orm import Session
from . import models

def get_action_by_id(db: Session, action_id: int):
    return db.query(models.Action).filter(models.Action.id == action_id).first()

def create_action(db: Session, action: models.Action):
    db.add(action)
    db.commit()
    db.refresh(action)
    return action
