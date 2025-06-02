from sqlalchemy.orm import Session
from app.models.audit_event import AuditEvent
from app.schemas.audit_event import AuditEventCreate


def create_audit_event(db: Session, obj_in: AuditEventCreate) -> AuditEvent:
    db_obj = AuditEvent(**obj_in.dict())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
