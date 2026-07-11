from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.console_target import ConsoleTarget as ConsoleTargetModel
from app.schemas.console_target import ConsoleTargetCreate, ConsoleTargetUpdate


def get(db: Session, target_id: int) -> Optional[ConsoleTargetModel]:
    return (
        db.query(ConsoleTargetModel).filter(ConsoleTargetModel.id == target_id).first()
    )


def get_multi_by_user(db: Session, user_id: int) -> List[ConsoleTargetModel]:
    return (
        db.query(ConsoleTargetModel)
        .filter(ConsoleTargetModel.user_id == user_id)
        .order_by(ConsoleTargetModel.name.asc())
        .all()
    )


def create(
    db: Session, obj_in: ConsoleTargetCreate, user_id: int
) -> ConsoleTargetModel:
    db_obj = ConsoleTargetModel(**obj_in.dict(), user_id=user_id)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(
    db: Session, db_obj: ConsoleTargetModel, obj_in: ConsoleTargetUpdate
) -> ConsoleTargetModel:
    for field, value in obj_in.dict(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def remove(db: Session, target_id: int) -> Optional[ConsoleTargetModel]:
    obj = get(db, target_id)
    if obj:
        db.delete(obj)
        db.commit()
    return obj
