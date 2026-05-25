import asyncio

from app import models
from app.core.config import settings
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
