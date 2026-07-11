from datetime import datetime

import pytest

from app import crud, models
from app.core.config import settings
from app.crud import routing as routing_crud
from app.crud.bot import create_bot
from app.routing import engine
from app.schemas.bot import BotCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.routing import RoutingRuleCreate
from app.schemas.user import UserCreate


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "routing_safety@example.com")
    if user:
        return user
    return crud.user.create_user(
        db,
        user=UserCreate(
            email="routing_safety@example.com",
            username="routing_safety",
            password="pass123",
        ),
    )


def _make_event_and_job(
    db,
    *,
    user_id: int,
    connector_id: int,
    connector_type: str,
    key: str,
    payload: dict,
    normalized: dict,
):
    event = models.RoutingEvent(
        user_id=user_id,
        connector_id=connector_id,
        connector_type=connector_type,
        message_text=payload.get("text"),
        payload=payload,
        status="queued",
        delivery_status="queued",
        idempotency_key=f"safety_{key}",
    )
    routing_crud.create_event(db, event)
    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector_id,
        status="pending",
        attempts=0,
        max_attempts=3,
        next_attempt_at=datetime.utcnow(),
        payload=payload,
        normalized=normalized,
    )
    routing_crud.create_job(db, job)
    return event, job


@pytest.mark.asyncio
async def test_routing_kill_switch_action_hold_blocks_delivery(db, monkeypatch):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack In", connector_type="slack", config={}),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack Out", connector_type="slack", config={}),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Hold Bot",
            description="hold",
            gpt_model="gpt-5-mini",
            session_id="hold",
        ),
        user_id=user.id,
    )
    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All to Slack Out",
            connector_id=source.id,
            connector_type="slack",
            destination_connector_id=destination.id,
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

    called = {"send": 0}

    class DummyConnector:
        def send_message(self, message):
            called["send"] += 1
            return {"status": "sent"}

    async def should_not_generate_reply(**kwargs):
        raise AssertionError(
            "bot reply should not be generated for untrusted provenance"
        )

    monkeypatch.setattr(engine, "_generate_bot_reply", should_not_generate_reply)
    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyConnector())

    _, job = _make_event_and_job(
        db,
        user_id=user.id,
        connector_id=source.id,
        connector_type=source.connector_type,
        key="hold",
        payload={"text": "hello"},
        normalized={"text": "hello"},
    )

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    settings.safety_kill_switch_level = 1
    try:
        status, event_id = await engine.process_routing_job(db=db, job=job)
    finally:
        settings.safety_kill_switch_level = prev_level

    assert status == "routed"
    assert event_id is not None
    event = routing_crud.get_event(db, int(event_id))
    assert event is not None
    assert event.delivery_status == "disabled"
    assert "kill-switch" in str(event.delivery_error or "").lower()
    assert called["send"] == 0


@pytest.mark.asyncio
async def test_routing_provenance_gate_blocks_untrusted_actions(db, monkeypatch):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Webhook In", connector_type="webhook", config={}),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack Out 2", connector_type="slack", config={}),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Provenance Bot",
            description="prov",
            gpt_model="gpt-5-mini",
            session_id="prov",
        ),
        user_id=user.id,
    )
    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All to Slack Out 2",
            connector_id=source.id,
            connector_type="webhook",
            destination_connector_id=destination.id,
            bot_id=bot.id,
            match_type="all",
            match_value=None,
            priority=100,
            is_active=True,
        ),
    )

    called = {"send": 0}

    class DummyConnector:
        def send_message(self, message):
            called["send"] += 1
            return {"status": "sent"}

    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyConnector())

    _, job = _make_event_and_job(
        db,
        user_id=user.id,
        connector_id=source.id,
        connector_type=source.connector_type,
        key="prov",
        payload={"text": "hello", "provenance": "untrusted"},
        normalized={"text": "hello", "provenance": "untrusted"},
    )

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    prev_enforce = getattr(settings, "safety_provenance_enforce", False)
    settings.safety_kill_switch_level = 0
    settings.safety_provenance_enforce = True
    try:
        status, event_id = await engine.process_routing_job(db=db, job=job)
    finally:
        settings.safety_kill_switch_level = prev_level
        settings.safety_provenance_enforce = prev_enforce

    assert status == "routed"
    assert event_id is not None
    event = routing_crud.get_event(db, int(event_id))
    assert event is not None
    assert event.delivery_status == "blocked_provenance"
    assert "untrusted" in str(event.delivery_error or "").lower()
    assert called["send"] == 0


@pytest.mark.asyncio
async def test_tmux_budget_trip_autolocks_connector(db, monkeypatch):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack In 3", connector_type="slack", config={}),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:budget",
            connector_type="tmux",
            config={
                "session": "budget",
                "target": "budget:0.0",
                "policy": {"budget_per_minute": 1},
            },
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Budget Bot",
            description="budget",
            gpt_model="gpt-5-mini",
            session_id="budget",
        ),
        user_id=user.id,
    )
    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All to tmux budget",
            connector_id=source.id,
            connector_type="slack",
            destination_connector_id=destination.id,
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

    class DummyTmux:
        def send_message(self, message):
            calls["send"] += 1
            return {"status": "sent"}

    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyTmux())

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    prev_autolock = getattr(settings, "safety_budget_autolock", True)
    settings.safety_kill_switch_level = 0
    settings.safety_budget_autolock = True
    try:
        _, first_job = _make_event_and_job(
            db,
            user_id=user.id,
            connector_id=source.id,
            connector_type=source.connector_type,
            key="budget_1",
            payload={"text": "hello 1"},
            normalized={"text": "hello 1"},
        )
        first_status, first_event_id = await engine.process_routing_job(
            db=db, job=first_job
        )
        assert first_status == "routed"
        assert first_event_id is not None

        _, second_job = _make_event_and_job(
            db,
            user_id=user.id,
            connector_id=source.id,
            connector_type=source.connector_type,
            key="budget_2",
            payload={"text": "hello 2"},
            normalized={"text": "hello 2"},
        )
        second_status, second_event_id = await engine.process_routing_job(
            db=db, job=second_job
        )
    finally:
        settings.safety_kill_switch_level = prev_level
        settings.safety_budget_autolock = prev_autolock

    assert second_status == "routed"
    assert second_event_id is not None
    event = routing_crud.get_event(db, int(second_event_id))
    assert event is not None
    assert event.delivery_status == "blocked_budget"
    assert "budget" in str(event.delivery_error or "").lower()

    db.expire_all()
    refreshed_dest = crud.connector.get(db, destination.id)
    assert bool((refreshed_dest.config or {}).get("locked")) is True
    assert "budget" in str((refreshed_dest.config or {}).get("locked_reason") or "")
    assert calls["send"] == 1


@pytest.mark.asyncio
async def test_tmux_operator_takeover_blocks_autonomous_delivery(db, monkeypatch):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="Slack In 4", connector_type="slack", config={}),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:takeover",
            connector_type="tmux",
            config={
                "session": "takeover",
                "target": "takeover:0.0",
                "operator_mode": "take",
                "operator_note": "manual takeover",
            },
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Takeover Bot",
            description="takeover",
            gpt_model="gpt-5-mini",
            session_id="takeover",
        ),
        user_id=user.id,
    )
    routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="All to tmux takeover",
            connector_id=source.id,
            connector_type="slack",
            destination_connector_id=destination.id,
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

    class DummyTmux:
        def send_message(self, message):
            calls["send"] += 1
            return {"status": "sent"}

    monkeypatch.setattr(engine, "get_connector", lambda *a, **k: DummyTmux())

    _, job = _make_event_and_job(
        db,
        user_id=user.id,
        connector_id=source.id,
        connector_type=source.connector_type,
        key="takeover",
        payload={"text": "hello"},
        normalized={"text": "hello"},
    )

    status, event_id = await engine.process_routing_job(db=db, job=job)

    assert status == "routed"
    assert event_id is not None
    event = routing_crud.get_event(db, int(event_id))
    assert event is not None
    assert event.delivery_status == "blocked_operator_takeover"
    assert "manual takeover" in str(event.delivery_error or "").lower()
    assert calls["send"] == 0
