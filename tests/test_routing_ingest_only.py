import asyncio

from app import models
from app.core.config import settings
from app.crud import routing as routing_crud
from app.routing import engine
from app.routing.engine import enqueue_routing_job


def test_enqueue_routing_job_ingest_only_skips_job(db):
    user = models.User(
        email="u_ingest@example.com",
        username="u_ingest",
        password="x",
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    connector = models.Connector(
        name="Webhook Inbox",
        connector_type="webhook",
        config={},
        user_id=user.id,
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    prev = getattr(settings, "routing_ingest_only", False)
    settings.routing_ingest_only = True
    try:
        before_events = db.query(models.RoutingEvent).count()
        before_jobs = db.query(models.RoutingJob).count()

        payload = {"text": "hello"}
        ret = asyncio.get_event_loop().run_until_complete(
            enqueue_routing_job(
                db=db,
                connector=connector,
                normalized=payload,
                payload=payload,
            )
        )

        assert ret["status"] == "logged"
        assert db.query(models.RoutingEvent).count() == before_events + 1
        assert db.query(models.RoutingJob).count() == before_jobs

        event = (
            db.query(models.RoutingEvent)
            .filter(models.RoutingEvent.id == ret["event_id"])
            .first()
        )
        assert event is not None
        assert event.status == "logged"
        assert event.delivery_status == "disabled"
    finally:
        settings.routing_ingest_only = prev


def test_process_routing_job_passive_without_rule_skips_bot_reply(db, monkeypatch):
    user = models.User(
        email="u_passive@example.com",
        username="u_passive",
        password="x",
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    connector = models.Connector(
        name="HAL Activity",
        connector_type="activity_monitor",
        config={"site": "knox", "zone": "office", "host": "hal"},
        user_id=user.id,
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    called = {"reply": 0}

    async def fake_reply(**kwargs):
        called["reply"] += 1
        return "unexpected"

    monkeypatch.setattr(engine, "_generate_bot_reply", fake_reply)

    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        message_text="[passive] hal office active",
        payload={"host": "hal", "zone": "office", "userActive": True},
        status="queued",
        delivery_status="queued",
        idempotency_key="passive_k1",
    )
    routing_crud.create_event(db, event)

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="pending",
        attempts=0,
        max_attempts=3,
        payload={"host": "hal", "zone": "office", "userActive": True},
        normalized={
            "text": "hal office active",
            "host": "hal",
            "zone": "office",
            "user_active": True,
            "screen_awake": True,
            "display_idle_seconds": 12,
            "signal_class": "passive",
            "passive_source": "activity_monitor",
        },
    )
    routing_crud.create_job(db, job)

    status, event_id = asyncio.get_event_loop().run_until_complete(
        engine.process_routing_job(db=db, job=job)
    )

    assert status == "received"
    assert event_id == event.id
    assert called["reply"] == 0

    updated = routing_crud.get_event(db, event.id)
    assert updated is not None
    assert updated.status == "received"
    assert updated.delivery_status == "disabled"
    assert updated.delivery_error == "passive signal stored; no routing rule"
