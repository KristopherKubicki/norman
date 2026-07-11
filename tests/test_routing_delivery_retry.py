from datetime import datetime

import pytest

from app import crud, models
from app.crud import routing as routing_crud
from app.schemas.bot import BotCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.routing import RoutingRuleCreate
from app.schemas.user import UserCreate
from app.crud.bot import create_bot
from app.routing import engine


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "routing_retry@example.com")
    if user:
        return user
    return crud.user.create_user(
        db,
        user=UserCreate(
            email="routing_retry@example.com",
            username="routing_retry",
            password="pass123",
        ),
    )


@pytest.mark.asyncio
async def test_process_routing_job_raises_on_delivery_failure(db, monkeypatch):
    user = _ensure_user(db)

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack", connector_type="slack", config={}),
        user_id=user.id,
    )

    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Retry Bot",
            description="retry",
            gpt_model="gpt-5-mini",
            session_id="retry",
        ),
        user_id=user.id,
    )

    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All",
            connector_id=connector.id,
            connector_type="slack",
            bot_id=bot.id,
            match_type="all",
            match_value=None,
            priority=100,
            is_active=True,
        ),
    )

    # Avoid calling LLM.
    async def fake_reply(**kwargs):
        return "ok"

    monkeypatch.setattr(engine, "_generate_bot_reply", fake_reply)

    class DummyConnector:
        def __init__(self, *a, **k):
            pass

        def is_connected(self):
            return True

        def send_message(self, message):
            raise RuntimeError("send failed")

    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyConnector())

    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        message_text="hello",
        payload={"text": "hello"},
        status="queued",
        delivery_status="queued",
        idempotency_key="k1",
    )
    routing_crud.create_event(db, event)

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="pending",
        attempts=0,
        max_attempts=3,
        next_attempt_at=datetime.utcnow(),
        payload={"text": "hello"},
        normalized={"text": "hello"},
    )
    routing_crud.create_job(db, job)

    with pytest.raises(engine.DeliveryFailed):
        await engine.process_routing_job(db=db, job=job)

    updated_event = routing_crud.get_event(db, event.id)
    assert updated_event
    assert updated_event.delivery_status == "failed"
    assert updated_event.delivery_error


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures(db, monkeypatch):
    engine.connector_circuit_breaker.reset()
    user = _ensure_user(db)

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack", connector_type="slack", config={}),
        user_id=user.id,
    )

    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Retry Bot",
            description="retry",
            gpt_model="gpt-5-mini",
            session_id="retry",
        ),
        user_id=user.id,
    )

    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All",
            connector_id=connector.id,
            connector_type="slack",
            bot_id=bot.id,
            match_type="all",
            match_value=None,
            priority=100,
            is_active=True,
        ),
    )

    async def fake_reply(**kwargs):
        return "ok"

    monkeypatch.setattr(engine, "_generate_bot_reply", fake_reply)

    calls = {"send": 0}

    class DummyConnector:
        def __init__(self, *a, **k):
            pass

        def is_connected(self):
            return True

        def send_message(self, message):
            calls["send"] += 1
            raise RuntimeError("send failed")

    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyConnector())

    def make_job(event_key: str):
        event = models.RoutingEvent(
            user_id=user.id,
            connector_id=connector.id,
            connector_type=connector.connector_type,
            message_text="hello",
            payload={"text": "hello"},
            status="queued",
            delivery_status="queued",
            idempotency_key=f"cb_{event_key}",
        )
        routing_crud.create_event(db, event)
        job = models.RoutingJob(
            event_id=event.id,
            connector_id=connector.id,
            status="pending",
            attempts=0,
            max_attempts=3,
            next_attempt_at=datetime.utcnow(),
            payload={"text": "hello"},
            normalized={"text": "hello"},
        )
        routing_crud.create_job(db, job)
        return job

    # 3 failures to open.
    for i in range(3):
        with pytest.raises(engine.DeliveryFailed):
            await engine.process_routing_job(db=db, job=make_job(f"k{i}"))

    assert calls["send"] == 3

    # Next attempt should trip circuit and not call send.
    with pytest.raises(Exception) as exc:
        await engine.process_routing_job(db=db, job=make_job("k3"))
    assert exc.value.__class__.__name__ == "CircuitOpen"
    assert calls["send"] == 3
