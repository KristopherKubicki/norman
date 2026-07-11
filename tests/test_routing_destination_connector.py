from datetime import datetime

import pytest

from app import crud, models
from app.crud import routing as routing_crud
from app.crud.bot import create_bot
from app.routing import engine
from app.schemas.bot import BotCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.routing import RoutingRuleCreate
from app.schemas.user import UserCreate


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "routing_dest@example.com")
    if user:
        return user
    return crud.user.create_user(
        db,
        user=UserCreate(
            email="routing_dest@example.com",
            username="routing_dest",
            password="pass123",
        ),
    )


@pytest.mark.asyncio
async def test_routing_rule_destination_connector_is_used_for_delivery(db, monkeypatch):
    user = _ensure_user(db)

    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack In", connector_type="slack", config={}),
        user_id=user.id,
    )
    dest = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Signal Out", connector_type="signal", config={}),
        user_id=user.id,
    )

    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Dest Bot",
            description="dest",
            gpt_model="gpt-5-mini",
            session_id="dest",
        ),
        user_id=user.id,
    )

    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All to Signal",
            connector_id=source.id,
            connector_type=source.connector_type,
            destination_connector_id=dest.id,
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

    calls = {"slack": 0, "signal": 0}

    class DummyConnector:
        def __init__(self, kind):
            self.kind = kind

        def is_connected(self):
            return True

        def send_message(self, message):
            calls[self.kind] += 1
            return {"result": "sent"}

    def fake_get_connector(connector_type, config):
        if connector_type == "signal":
            return DummyConnector("signal")
        if connector_type == "slack":
            return DummyConnector("slack")
        raise AssertionError(f"unexpected connector_type {connector_type}")

    monkeypatch.setattr(engine, "get_connector", fake_get_connector)

    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=source.id,
        connector_type=source.connector_type,
        message_text="hello",
        payload={"text": "hello"},
        status="queued",
        delivery_status="queued",
        idempotency_key="dest_k1",
    )
    routing_crud.create_event(db, event)

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=source.id,
        status="pending",
        attempts=0,
        max_attempts=3,
        next_attempt_at=datetime.utcnow(),
        payload={"text": "hello"},
        normalized={"text": "hello"},
    )
    routing_crud.create_job(db, job)

    status, event_id = await engine.process_routing_job(db=db, job=job)
    assert status == "routed"
    assert event_id == event.id

    updated = routing_crud.get_event(db, event.id)
    assert updated
    assert updated.delivery_status == "sent"
    assert updated.destination_connector_id == dest.id
    assert updated.destination_connector_type == dest.connector_type

    assert calls["slack"] == 0
    assert calls["signal"] == 1


@pytest.mark.asyncio
async def test_reply_webhook_payload_carries_sms_reply_context(db, monkeypatch):
    user = _ensure_user(db)

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="SMS In",
            connector_type="sms",
            config={"reply_webhook_url": "https://bridge.invalid/twilio/sms/send"},
        ),
        user_id=user.id,
    )

    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="SMS Bot",
            description="sms",
            gpt_model="gpt-5-mini",
            session_id="sms",
        ),
        user_id=user.id,
    )

    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="SMS All",
            connector_id=connector.id,
            connector_type=connector.connector_type,
            bot_id=bot.id,
            match_type="all",
            match_value=None,
            priority=100,
            is_active=True,
        ),
    )

    async def fake_reply(**kwargs):
        return "reply text"

    monkeypatch.setattr(engine, "_generate_bot_reply", fake_reply)

    captured = {}

    class DummyWebhookConnector:
        def __init__(self, webhook_url, config=None):
            captured["webhook_url"] = webhook_url
            captured["config"] = dict(config or {})

        async def send_message(self, message):
            captured["message"] = message
            return "ok"

    monkeypatch.setattr(engine, "WebhookConnector", DummyWebhookConnector)

    event = models.RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        message_text="hello",
        payload={"Body": "hello", "From": "+15551230000", "To": "+15557654321"},
        status="queued",
        delivery_status="queued",
        idempotency_key="sms_reply_k1",
    )
    routing_crud.create_event(db, event)

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="pending",
        attempts=0,
        max_attempts=3,
        next_attempt_at=datetime.utcnow(),
        payload={"Body": "hello", "From": "+15551230000", "To": "+15557654321"},
        normalized={"text": "hello", "from": "+15551230000", "to": "+15557654321"},
    )
    routing_crud.create_job(db, job)

    status, event_id = await engine.process_routing_job(db=db, job=job)
    assert status == "routed"
    assert event_id == event.id
    assert captured["webhook_url"] == "https://bridge.invalid/twilio/sms/send"
    assert captured["message"]["text"] == "reply text"
    assert captured["message"]["reply_to"] == "+15551230000"
    assert captured["message"]["reply_from"] == "+15557654321"
    assert captured["message"]["source_connector_type"] == "sms"
    assert captured["message"]["source_normalized"]["from"] == "+15551230000"
