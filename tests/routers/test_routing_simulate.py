from app import crud
from app.crud.bot import create_bot
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


def test_routing_simulate_matches_rule(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack In",
            connector_type="slack",
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
    crud.routing.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Proxy Rule",
            connector_id=connector.id,
            connector_type="slack",
            bot_id=bot.id,
            match_type="contains",
            match_value="proxy",
            priority=100,
            is_active=True,
        ),
    )

    resp = test_app.post(
        "/api/v1/routing/simulate",
        json={
            "connector_id": connector.id,
            "message_text": "please proxy this now",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "matched_rule"
    assert data["selected_bot_id"] == bot.id
    assert len(data["matches"]) == 1
    assert data["matches"][0]["rule_name"] == "Proxy Rule"


def test_routing_simulate_fallback_bot(test_app, db):
    user = _ensure_user(db)
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Welcome Bot",
            description="welcome",
            gpt_model="gpt-5-mini",
            session_id="welcome",
        ),
        user_id=user.id,
    )

    resp = test_app.post(
        "/api/v1/routing/simulate",
        json={"message_text": "no rules for this"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "fallback_bot"
    assert data["selected_bot_id"] == bot.id


def test_routing_simulate_matches_passive_rule(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="SNMP Sensor",
            connector_type="snmp",
            config={},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Passive Bot",
            description="passive",
            gpt_model="gpt-5-mini",
            session_id="passive",
        ),
        user_id=user.id,
    )
    crud.routing.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Passive SNMP Rule",
            connector_id=connector.id,
            connector_type="snmp",
            bot_id=bot.id,
            match_type="passive",
            match_value="snmp",
            priority=100,
            is_active=True,
        ),
    )

    resp = test_app.post(
        "/api/v1/routing/simulate",
        json={
            "connector_id": connector.id,
            "message_text": "trap: link down",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "matched_rule"
    assert data["selected_bot_id"] == bot.id
    assert data["matches"][0]["rule_name"] == "Passive SNMP Rule"


def test_routing_simulate_reports_shadow_match(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Webhook Shadow",
            connector_type="webhook",
            config={},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Shadow Preview Bot",
            description="shadow",
            gpt_model="gpt-5-mini",
            session_id="shadow-preview",
        ),
        user_id=user.id,
    )
    crud.routing.create_rule(
        db,
        user_id=user.id,
        rule_in=RoutingRuleCreate(
            name="Shadow Rule",
            connector_id=connector.id,
            connector_type="webhook",
            bot_id=bot.id,
            match_type="contains",
            match_value="proxy",
            priority=100,
            is_active=False,
        ),
    )

    resp = test_app.post(
        "/api/v1/routing/simulate",
        json={
            "connector_id": connector.id,
            "message_text": "proxy route this",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "shadow_match"
    assert data["selected_rule_id"] is None
    assert len(data["matches"]) == 1
    assert data["matches"][0]["is_active"] is False
