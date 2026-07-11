from app import crud
from app.core.config import settings
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


def test_create_routing_rule_rejects_self_destination(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Norman",
            connector_type="tmux",
            config={"session": "norman"},
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
    resp = test_app.post(
        "/api/v1/routing/rules",
        json={
            "name": "Self loop",
            "connector_id": connector.id,
            "connector_type": "tmux",
            "destination_connector_id": connector.id,
            "bot_id": bot.id,
            "match_type": "all",
            "priority": 10,
            "is_active": True,
        },
    )
    assert resp.status_code == 400
    assert "must be different" in str(resp.json().get("detail", "")).lower()


def test_update_routing_rule_rejects_self_destination(test_app, db):
    user = _ensure_user(db)
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Norman",
            connector_type="tmux",
            config={"session": "norman"},
        ),
        user_id=user.id,
    )
    destination = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Castle",
            connector_type="tmux",
            config={"session": "castle"},
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
            name="Norman to Castle",
            connector_id=source.id,
            connector_type="tmux",
            destination_connector_id=destination.id,
            bot_id=bot.id,
            match_type="all",
            priority=20,
            is_active=True,
        ),
    )

    resp = test_app.put(
        f"/api/v1/routing/rules/{rule.id}",
        json={"destination_connector_id": source.id},
    )
    assert resp.status_code == 400
    assert "must be different" in str(resp.json().get("detail", "")).lower()


def test_create_routing_rule_defaults_to_shadow_when_enabled(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Norman Shadow",
            connector_type="tmux",
            config={"session": "norman-shadow"},
        ),
        user_id=user.id,
    )
    bot = create_bot(
        db,
        bot_create=BotCreate(
            name="Shadow Bot",
            description="shadow",
            gpt_model="gpt-5-mini",
            session_id="shadow",
        ),
        user_id=user.id,
    )

    prev = getattr(settings, "safety_shadow_rules_default", False)
    settings.safety_shadow_rules_default = True
    try:
        resp = test_app.post(
            "/api/v1/routing/rules",
            json={
                "name": "Shadow by default",
                "connector_id": connector.id,
                "connector_type": "tmux",
                "destination_connector_id": None,
                "bot_id": bot.id,
                "match_type": "all",
                "priority": 10,
                "is_active": True,
            },
        )
    finally:
        settings.safety_shadow_rules_default = prev

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["is_active"] is False
