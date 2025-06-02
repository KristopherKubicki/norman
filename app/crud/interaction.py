from sqlalchemy.orm import Session
from app.models import Interaction
from app.schemas.interaction import InteractionCreate


def get_interaction_by_id(db: Session, interaction_id: int) -> Interaction:
    """Return an interaction by its ID."""
    return db.query(Interaction).filter(Interaction.id == interaction_id).first()


def create_interaction(db: Session, interaction: InteractionCreate) -> Interaction:
    """Persist a new interaction to the database."""
    db_interaction = Interaction(**interaction.dict())
    db.add(db_interaction)
    db.commit()
    db.refresh(db_interaction)
    return db_interaction


def get_all_interactions(db: Session):
    """Return all interactions."""
    return db.query(Interaction).all()


def delete_interaction(db: Session, interaction_id: int):
    """Delete an interaction by ID."""
    interaction = get_interaction_by_id(db, interaction_id)
    if interaction:
        db.delete(interaction)
        db.commit()
        return True
    return False

