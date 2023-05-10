from sqlalchemy.orm import Session
from app.models import Interaction
from app.schemas.interaction import InteractionCreate


def get_interaction_by_id(db: Session, interaction_id: int) -> Interaction:
    return db.query(Interaction).filter(Interaction.id == interaction_id).first()


def create_interaction(db: Session, interaction: InteractionCreate) -> Interaction:
    db_interaction = Interaction(**interaction.dict())
    db.add(db_interaction)
    db.commit()
    db.refresh(db_interaction)
    return db_interaction


def get_all_interactions(db: Session):
    return db.query(Interaction).all()


def delete_interaction(db: Session, interaction_id: int):
    interaction = get_interaction_by_id(db, interaction_id)
    if interaction:
        db.delete(interaction)
        db.commit()
        return True
    return False

