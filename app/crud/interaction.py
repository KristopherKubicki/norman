from sqlalchemy.orm import Session
from . import models

def get_interaction_by_id(db: Session, interaction_id: int):
    return db.query(models.Interaction).filter(models.Interaction.id == interaction_id).first()

def create_interaction(db: Session, interaction: models.Interaction):
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction
