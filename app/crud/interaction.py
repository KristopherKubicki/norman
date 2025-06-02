from sqlalchemy.orm import Session
from typing import List, Optional, cast

from app.models import Interaction
from app.schemas.interaction import InteractionCreate


def get_interaction_by_id(db: Session, interaction_id: int) -> Optional[Interaction]:
    return db.query(Interaction).filter(Interaction.id == interaction_id).first()


def create_interaction(db: Session, interaction: InteractionCreate) -> Interaction:
    db_interaction = Interaction(**interaction.dict())
    db.add(db_interaction)
    db.commit()
    db.refresh(db_interaction)
    return db_interaction


def get_all_interactions(db: Session) -> List[Interaction]:
    interactions = db.query(Interaction).all()
    return cast(List[Interaction], interactions)


def delete_interaction(db: Session, interaction_id: int) -> bool:
    interaction = get_interaction_by_id(db, interaction_id)
    if interaction:
        db.delete(interaction)
        db.commit()
        return True
    return False

