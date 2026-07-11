from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import crud
from app.schemas.connector import ConnectorCreate
from app.schemas.routing import RoutingRuleCreate
from app.schemas.user import UserCreate
from app.crud.bot import create_bot
from app.schemas.bot import BotCreate
from app.services.connector_health import ConnectorHealthHistoryEntry


def test_test_connector_endpoint(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="irc1", connector_type="irc", config={}),
        user_id=user.id,
    )

    class DummyConnector:
        def is_connected(self):
            return True

    monkeypatch.setattr(
        "app.app_routes.get_connector", lambda *a, **k: DummyConnector()
    )

    resp = test_app.post(f"/api/connectors/{connector.id}/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_connector_status_endpoint(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="irc2", connector_type="irc", config={}),
        user_id=user.id,
    )

    class DummyConnector:
        def is_connected(self):
            return False

    monkeypatch.setattr(
        "app.app_routes.get_connector", lambda *a, **k: DummyConnector()
    )

    resp = test_app.get(f"/api/connectors/{connector.id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "down"
    assert "last_message_sent" in data


def test_connector_diagnose_endpoint(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="irc-diagnose",
            connector_type="irc",
            config={"server": "irc.example.com", "port": "6697", "use_ssl": "true"},
        ),
        user_id=user.id,
    )

    class DummyConnector:
        def is_connected(self):
            return False

    monkeypatch.setattr(
        "app.app_routes.get_connector", lambda *a, **k: DummyConnector()
    )

    resp = test_app.get(f"/api/connectors/{connector.id}/diagnose")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "down"
    assert data["connector_id"] == connector.id
    assert "recommended_actions" in data


def test_connectors_list_cache_header(test_app: TestClient) -> None:
    resp = test_app.get("/api/connectors")
    assert resp.status_code == 200
    assert (
        resp.headers.get("cache-control")
        == "private, max-age=15, stale-while-revalidate=30"
    )


def test_bulk_connector_statuses_endpoint(test_app: TestClient) -> None:
    resp = test_app.get("/api/v1/connectors/statuses")
    assert resp.status_code == 200
    payload = resp.json()
    assert "items" in payload
    assert "count" in payload


def test_connector_status_history_endpoint(
    test_app: TestClient, db: Session, monkeypatch
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(name="irc-history", connector_type="irc", config={}),
        user_id=user.id,
    )

    history = [
        ConnectorHealthHistoryEntry(
            connector_id=connector.id,
            connector_type="irc",
            status="down",
            checked_at=1710000000.0,
            failures=2,
            error="dial timeout",
        ),
        ConnectorHealthHistoryEntry(
            connector_id=connector.id,
            connector_type="irc",
            status="up",
            checked_at=1709999940.0,
            failures=0,
            error="",
        ),
    ]

    async def fake_get_history(connector_id: int, *, limit=None):
        return history[:limit] if limit else history

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.connector_health.get_history",
        fake_get_history,
    )

    resp = test_app.get(
        f"/api/v1/connectors/statuses/history?connector_id={connector.id}"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["connector_id"] == connector.id
    assert payload["connector_name"] == "irc-history"
    assert len(payload["history"]) == 2
    assert payload["recent_errors"][0]["error"] == "dial timeout"


def test_connector_bundle_export_omits_oauth_and_includes_routing_rules(
    test_app: TestClient, db: Session
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack Export",
            connector_type="slack",
            config={
                "channel_id": "#ops-export",
                "oauth_access_token": "secret-token",
                "oauth_provider": "google",
            },
        ),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="TMUX Export",
            connector_type="tmux",
            config={"session": "ops-export"},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Ops Export Bot",
            description="export",
            gpt_model="gpt-5-mini",
            session_id="ops-export",
        ),
        user_id=user.id,
    )
    crud.routing.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Export Rule",
            connector_id=source.id,
            connector_type=source.connector_type,
            destination_connector_id=destination.id,
            bot_id=bot.id,
            match_type="contains",
            match_value="incident",
            priority=55,
            is_active=True,
        ),
    )

    resp = test_app.get("/api/v1/connectors/export")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["version"] == 1
    slack_bundle = next(
        item for item in payload["connectors"] if item["name"] == "Slack Export"
    )
    assert slack_bundle["config"]["channel_id"] == "#ops-export"
    assert "oauth_access_token" not in slack_bundle["config"]
    assert "oauth_provider" not in slack_bundle["config"]
    assert payload["routing_rules"][0]["name"] == "Export Rule"
    assert payload["routing_rules"][0]["connector_name"] == "Slack Export"
    assert payload["routing_rules"][0]["destination_connector_name"] == "TMUX Export"
    assert payload["routing_rules"][0]["bot_session_id"] == "ops-export"


def test_connector_bundle_import_upserts_connectors_and_rules(
    test_app: TestClient, db: Session
) -> None:
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Ops Import Bot",
            description="import",
            gpt_model="gpt-5-mini",
            session_id="ops-import",
        ),
        user_id=user.id,
    )

    bundle = {
        "version": 1,
        "connectors": [
            {
                "name": "Slack Import",
                "connector_type": "slack",
                "config": {"channel_id": "#ops-import"},
            },
            {
                "name": "TMUX Import",
                "connector_type": "tmux",
                "config": {"session": "ops-import"},
            },
        ],
        "routing_rules": [
            {
                "name": "Import Rule",
                "connector_name": "Slack Import",
                "connector_type": "slack",
                "destination_connector_name": "TMUX Import",
                "destination_connector_type": "tmux",
                "bot_name": bot.name,
                "bot_session_id": bot.session_id,
                "match_type": "contains",
                "match_value": "page me",
                "priority": 15,
                "is_active": True,
            }
        ],
    }

    resp = test_app.post("/api/v1/connectors/import", json=bundle)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["connectors_created"] == 2
    assert payload["connectors_updated"] == 0
    assert payload["routing_rules_created"] == 1
    assert payload["routing_rules_updated"] == 0

    created_connectors = crud.connector.get_multi_by_user(db, user.id)
    slack = next(
        connector
        for connector in created_connectors
        if connector.name == "Slack Import"
    )
    tmux = next(
        connector for connector in created_connectors if connector.name == "TMUX Import"
    )
    assert slack.config["channel_id"] == "#ops-import"
    imported_rule = next(
        rule
        for rule in crud.routing.get_rules_by_user(db, user.id)
        if rule.name == "Import Rule"
    )
    assert imported_rule.connector_id == slack.id
    assert imported_rule.destination_connector_id == tmux.id
    assert imported_rule.bot_id == bot.id
    assert imported_rule.priority == 15

    bundle["connectors"][0]["config"]["channel_id"] = "#ops-reimport"
    bundle["routing_rules"][0]["priority"] = 42
    resp = test_app.post("/api/v1/connectors/import", json=bundle)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["connectors_created"] == 0
    assert payload["connectors_updated"] == 1
    assert payload["routing_rules_created"] == 0
    assert payload["routing_rules_updated"] == 1

    db.refresh(slack)
    db.refresh(imported_rule)
    assert slack.config["channel_id"] == "#ops-reimport"
    assert imported_rule.priority == 42
