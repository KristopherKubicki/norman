from datetime import datetime, timedelta

from app import crud, models
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate
from app.services.operator_state import build_operator_state


def _seed_passive_job(
    db,
    *,
    user_id: int,
    connector,
    payload: dict,
    normalized: dict,
    key: str,
    created_at: datetime | None = None,
):
    event = models.RoutingEvent(
        user_id=user_id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        message_text=normalized.get("text_summary") or normalized.get("text") or "",
        payload=payload,
        status="received",
        delivery_status="skipped",
        idempotency_key=key,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="done",
        attempts=1,
        max_attempts=5,
        payload=payload,
        normalized=normalized,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if created_at is not None:
        event.created_at = created_at
        job.created_at = created_at
        job.updated_at = created_at
        db.add(event)
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


def test_operator_state_endpoint_merges_hubitat_and_activity_monitor(test_app, db):
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )

    hubitat = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Hubitat Knox",
            connector_type="hubitat",
            config={"hub_id": "knox"},
        ),
        user_id=user.id,
    )
    activity = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="HAL Activity",
            connector_type="activity_monitor",
            config={"site": "knox", "zone": "office", "host": "hal"},
        ),
        user_id=user.id,
    )

    _seed_passive_job(
        db,
        user_id=user.id,
        connector=hubitat,
        payload={
            "displayName": "Kris Presence",
            "name": "presence",
            "value": "present",
        },
        normalized={
            "text": "Kris Presence presence present",
            "text_summary": "hubitat • Kris Presence • presence • present",
            "device": "Kris Presence",
            "attribute": "presence",
            "value": "present",
            "signal_class": "passive",
            "passive_source": "hubitat",
            "sensor_type": "home_automation",
        },
        key="operator-state-home",
    )
    _seed_passive_job(
        db,
        user_id=user.id,
        connector=hubitat,
        payload={"displayName": "Office Presence", "name": "motion", "value": "active"},
        normalized={
            "text": "Office Presence motion active",
            "text_summary": "hubitat • Office Presence • motion • active",
            "device": "Office Presence",
            "attribute": "motion",
            "value": "active",
            "signal_class": "passive",
            "passive_source": "hubitat",
            "sensor_type": "home_automation",
        },
        key="operator-state-office",
    )
    _seed_passive_job(
        db,
        user_id=user.id,
        connector=activity,
        payload={"host": "hal", "userActive": True},
        normalized={
            "text": "hal office active",
            "text_summary": "activity • hal • office • active • idle 14s",
            "host": "hal",
            "zone": "office",
            "site": "knox",
            "user_active": True,
            "screen_awake": True,
            "session_locked": False,
            "display_idle_seconds": 14,
            "signal_class": "passive",
            "passive_source": "activity_monitor",
            "sensor_type": "activity",
        },
        key="operator-state-workstation",
    )

    resp = test_app.get("/api/v1/operator-state/current")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "office_active"
    assert payload["home_present"] is True
    assert payload["office_present"] is True
    assert payload["workstation_active"] is True
    assert payload["screen_awake"] is True
    assert payload["display_idle_seconds"] == 14
    assert {item["kind"] for item in payload["sources"]} == {
        "home_presence",
        "office_presence",
        "workstation_activity",
    }


def test_operator_state_office_motion_expires_after_ten_minutes(db):
    user = crud.user.create_user(
        db,
        user=UserCreate(
            email="test_stale_office@example.com",
            username="test_stale_office",
            password="pass123",
        ),
    )

    hubitat = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Hubitat Knox",
            connector_type="hubitat",
            config={"hub_id": "knox"},
        ),
        user_id=user.id,
    )

    now = datetime.utcnow()
    _seed_passive_job(
        db,
        user_id=user.id,
        connector=hubitat,
        payload={
            "displayName": "Kris Presence",
            "name": "presence",
            "value": "present",
        },
        normalized={
            "text": "Kris Presence presence present",
            "text_summary": "hubitat • Kris Presence • presence • present",
            "device": "Kris Presence",
            "attribute": "presence",
            "value": "present",
            "signal_class": "passive",
            "passive_source": "hubitat",
            "sensor_type": "home_automation",
        },
        key="operator-state-home-fresh",
        created_at=now - timedelta(minutes=2),
    )
    _seed_passive_job(
        db,
        user_id=user.id,
        connector=hubitat,
        payload={"displayName": "Office Presence", "name": "motion", "value": "active"},
        normalized={
            "text": "Office Presence motion active",
            "text_summary": "hubitat • Office Presence • motion • active",
            "device": "Office Presence",
            "attribute": "motion",
            "value": "active",
            "signal_class": "passive",
            "passive_source": "hubitat",
            "sensor_type": "home_automation",
        },
        key="operator-state-office-stale",
        created_at=now - timedelta(minutes=11),
    )

    payload = build_operator_state(db, user_id=user.id)
    assert payload.state == "home_idle"
    office = next(item for item in payload.sources if item.kind == "office_presence")
    assert office.fresh is False
