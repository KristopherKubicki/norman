from datetime import datetime, timedelta

from app import crud, models
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com",
                username="test_user",
                password="pass123",
            ),
        )
    return user


def test_routing_jobs_endpoint_exposes_dead_letter_context(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack Out",
            connector_type="slack",
            config={},
        ),
        user_id=user.id,
    )
    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type="slack",
        message_text="delivery failed",
        status="dead_letter",
        delivery_status="dead_letter",
        error="retry budget exhausted",
        delivery_error="connector timed out",
        created_at=datetime.utcnow(),
        idempotency_key="routing_job_dead_letter",
    )
    event = crud.routing.create_event(db, event)
    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="dead",
        attempts=5,
        max_attempts=5,
        next_attempt_at=datetime.utcnow() + timedelta(minutes=5),
        last_error="connector timed out",
    )
    job = crud.routing.create_job(db, job)

    resp = test_app.get("/api/v1/routing/jobs?include_done=true")
    assert resp.status_code == 200
    payload = resp.json()
    row = next((item for item in payload if item["id"] == job.id), None)
    assert row is not None
    assert row["status"] == "dead"
    assert row["event_status"] == "dead_letter"
    assert row["event_delivery_status"] == "dead_letter"
    assert row["event_delivery_error"] == "connector timed out"
    assert row["message_text"] == "delivery failed"
    assert isinstance(row.get("next_attempt_at"), str)


def test_retry_routing_job_resets_dead_letter_state(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Signal Out",
            connector_type="signal",
            config={},
        ),
        user_id=user.id,
    )
    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type="signal",
        message_text="retry me",
        status="dead_letter",
        delivery_status="dead_letter",
        error="dead letter",
        delivery_error="socket hangup",
        created_at=datetime.utcnow(),
        idempotency_key="routing_job_retry",
    )
    event = crud.routing.create_event(db, event)
    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="dead",
        attempts=3,
        max_attempts=3,
        next_attempt_at=datetime.utcnow() + timedelta(hours=1),
        last_error="socket hangup",
    )
    job = crud.routing.create_job(db, job)

    resp = test_app.post(f"/api/v1/routing/jobs/{job.id}/retry")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "pending"
    assert payload["attempts"] == 0
    assert payload["last_error"] is None
    assert payload["event_status"] == "queued"
    assert payload["event_delivery_status"] == "queued"
    assert payload["event_delivery_error"] is None

    db.expire_all()
    updated_job = crud.routing.get_job(db, job.id)
    updated_event = crud.routing.get_event(db, event.id)
    assert updated_job is not None
    assert updated_job.status == "pending"
    assert updated_job.attempts == 0
    assert updated_job.last_error is None
    assert updated_event is not None
    assert updated_event.status == "queued"
    assert updated_event.delivery_status == "queued"
    assert updated_event.error is None
    assert updated_event.delivery_error is None
