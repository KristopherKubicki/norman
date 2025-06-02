from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import crud
from app.schemas.user import UserCreate
from app.models.audit_event import AuditEvent
from app.tests.utils.utils import random_email, random_lower_string


def test_login_audit_recorded(test_app: TestClient, db: Session):
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()
    user = crud.user.create_user(db, UserCreate(email=email, password=password, username=username))

    resp = test_app.post("/login", data={"username": email, "password": password}, follow_redirects=False)
    assert resp.status_code == 303

    event = db.query(AuditEvent).filter(AuditEvent.user_id == user.id).first()
    assert event is not None
    assert event.event_type == "login_success"
