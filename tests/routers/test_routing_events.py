from datetime import datetime

from app import crud
from app.models.routing import RoutingEvent, RoutingJob
from app.schemas.connector import ConnectorCreate
from app.schemas.bot import BotCreate
from app.schemas.routing import RoutingRuleCreate
from app.schemas.user import UserCreate
from app.crud.bot import create_bot


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


def test_routing_events_endpoint_serializes_datetime(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Tmux Route",
            connector_type="tmux",
            config={},
        ),
        user_id=user.id,
    )
    event = RoutingEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_type="tmux",
        destination_connector_id=None,
        destination_connector_type=None,
        bot_id=None,
        rule_id=None,
        message_text="hello route",
        status="received",
        delivery_status="queued",
        error=None,
        delivery_error=None,
        created_at=datetime.utcnow(),
    )
    event = crud.routing.create_event(db, event)

    resp = test_app.get("/api/v1/routing/events")
    assert resp.status_code == 200
    payload = resp.json()
    row = next((item for item in payload if item["id"] == event.id), None)
    assert row is not None
    assert isinstance(row.get("created_at"), str)
    assert "T" in row["created_at"]


def test_routing_event_trace_endpoint_returns_rule_bot_and_job_context(test_app, db):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack In",
            connector_type="slack",
            config={},
        ),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Signal Out",
            connector_type="signal",
            config={},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Ops Bot",
            description="ops",
            gpt_model="gpt-5-mini",
            session_id="ops",
        ),
        user_id=user.id,
    )
    rule = crud.routing.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Proxy Rule",
            connector_id=source.id,
            connector_type="slack",
            destination_connector_id=destination.id,
            bot_id=bot.id,
            match_type="contains",
            match_value="proxy",
            priority=100,
            is_active=True,
        ),
    )
    event = RoutingEvent(
        user_id=user.id,
        connector_id=source.id,
        connector_type="slack",
        destination_connector_id=destination.id,
        destination_connector_type="signal",
        bot_id=bot.id,
        rule_id=rule.id,
        message_text="please proxy this",
        status="queued",
        delivery_status="dead_letter",
        error="retry budget exhausted",
        delivery_error="connector timed out",
        created_at=datetime.utcnow(),
        idempotency_key="routing_trace_event",
    )
    event = crud.routing.create_event(db, event)
    crud.routing.create_job(
        db,
        RoutingJob(
            event_id=event.id,
            connector_id=destination.id,
            status="dead",
            attempts=5,
            max_attempts=5,
            last_error="connector timed out",
        ),
    )

    resp = test_app.get(f"/api/v1/routing/events/{event.id}/trace")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["decision"] == "matched_rule"
    assert payload["source_connector"]["name"] == "Slack In"
    assert payload["destination_connector"]["name"] == "Signal Out"
    assert payload["bot"]["name"] == "Ops Bot"
    assert payload["rule"]["name"] == "Proxy Rule"
    assert payload["latest_job"]["status"] == "dead"
    assert any("Rule matched" in line for line in payload["explanation"])
