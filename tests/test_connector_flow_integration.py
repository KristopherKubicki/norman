import asyncio
from urllib.parse import parse_qs, urlparse

import app.api.api_v1.routers.connectors_crud as connectors_crud_router

from app import crud
from app.crud.bot import create_bot
from app.crud import routing as routing_crud
from app.routing import engine
from app.schemas.bot import BotCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.routing import RoutingRuleCreate
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


def test_connector_oauth_round_trip_consumes_real_pending_state(
    test_app, db, monkeypatch
):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack OAuth Integration",
            connector_type="slack",
            config={"channel_id": "C123"},
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        connectors_crud_router,
        "resolve_oauth_binding",
        lambda connector_type, provider=None: {
            "provider": "google",
            "token_field": "token",
            "scopes": ["openid", "email"],
        },
    )
    monkeypatch.setattr(
        connectors_crud_router.settings,
        "google_client_id",
        "google-client-id",
        raising=False,
    )
    monkeypatch.setattr(
        connectors_crud_router.settings,
        "google_client_secret",
        "google-client-secret",
        raising=False,
    )

    class DummyResp:
        ok = True

        @staticmethod
        def json():
            return {
                "access_token": "token_123",
                "refresh_token": "refresh_456",
                "expires_in": 3600,
            }

    monkeypatch.setattr(
        connectors_crud_router.requests, "post", lambda *a, **k: DummyResp()
    )

    start_resp = test_app.get(
        f"/api/v1/connectors/oauth/start?connector_type=slack&connector_id={connector.id}&provider=google"
    )
    assert start_resp.status_code == 303
    parsed = urlparse(start_resp.headers["location"])
    state = parse_qs(parsed.query)["state"][0]

    callback_resp = test_app.get(
        f"/api/v1/connectors/oauth/callback/google?code=ok&state={state}"
    )
    assert callback_resp.status_code == 303
    assert "/connectors.html?oauth=success" in callback_resp.headers["location"]

    check = test_app.get(f"/api/v1/connectors/{connector.id}")
    assert check.status_code == 200
    payload = check.json()
    assert payload["config"]["token"] == "token_123"
    assert payload["config"]["oauth_provider"] == "google"
    assert payload["config"]["oauth_refresh_token"] == "refresh_456"
    assert payload["config"]["oauth_expires_at"] > 0

    replay_resp = test_app.get(
        f"/api/v1/connectors/oauth/callback/google?code=ok&state={state}"
    )
    assert replay_resp.status_code == 303
    assert "/connectors.html?oauth=error" in replay_resp.headers["location"]


def test_generic_webhook_routing_flow_round_trip(test_app, db, monkeypatch):
    user = _ensure_user(db)
    integration_text = "please page me now [routing integration]"
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Webhook Source Integration",
            connector_type="webhook",
            config={"webhook_url": "https://example.invalid/inbound"},
        ),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack Destination Integration",
            connector_type="slack",
            config={"channel_id": "#ops"},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Routing Integration Bot",
            description="integration",
            gpt_model="gpt-5-mini",
            session_id="routing-integration",
        ),
        user_id=user.id,
    )

    rule = routing_crud.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Webhook To Slack Integration",
            connector_id=source.id,
            connector_type="webhook",
            destination_connector_id=destination.id,
            bot_id=bot.id,
            match_type="contains",
            match_value="page me",
            priority=999,
            is_active=True,
        ),
    )

    class DummyInboundConnector:
        def process_incoming(self, payload):
            return {"text": payload.get("text", ""), "source": "integration-test"}

    delivered = {}

    class DummyDeliveryConnector:
        def send_message(self, message):
            delivered["message"] = message
            return {"result": "ok"}

    async def fake_reply(**kwargs):
        return "assistant says hi"

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors.generic.get_connector",
        lambda *a, **k: DummyInboundConnector(),
    )
    monkeypatch.setattr(
        engine, "get_connector", lambda *a, **k: DummyDeliveryConnector()
    )
    monkeypatch.setattr(engine, "_generate_bot_reply", fake_reply)

    ingest_resp = test_app.post(
        f"/api/v1/connectors/webhooks/webhook/{source.id}",
        json={"text": integration_text},
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "ok"

    jobs_resp = test_app.get("/api/v1/routing/jobs")
    assert jobs_resp.status_code == 200
    jobs = [
        job
        for job in jobs_resp.json()
        if job["event_connector_id"] == source.id
        and integration_text in (job.get("message_text") or "")
    ]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["destination_connector_id"] is None

    events_resp = test_app.get("/api/v1/routing/events")
    assert events_resp.status_code == 200
    events = [
        event
        for event in events_resp.json()
        if event["connector_id"] == source.id
        and integration_text in (event.get("message_text") or "")
    ]
    assert len(events) == 1
    assert events[0]["delivery_status"] == "queued"

    job_id = jobs[0]["id"]
    job = routing_crud.get_job(db, job_id)
    assert job is not None
    status, event_id = asyncio.run(engine.process_routing_job(db=db, job=job))
    assert status == "routed"
    assert event_id is not None

    event = routing_crud.get_event(db, int(event_id))
    assert event is not None
    assert event.delivery_status == "sent"
    assert event.destination_connector_id == destination.id
    assert event.rule_id == rule.id
    assert event.bot_id == bot.id
    assert delivered["message"] == "assistant says hi"

    trace_resp = test_app.get(f"/api/v1/routing/events/{event.id}/trace")
    assert trace_resp.status_code == 200
    trace = trace_resp.json()
    assert trace["decision"] == "matched_rule"
    assert trace["destination_connector"]["id"] == destination.id
    assert trace["latest_job"]["id"] == job.id
