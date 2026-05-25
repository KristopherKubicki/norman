import app.app_routes as app_routes
from app.core.config import settings
from app.crud.user import get_user_by_email


def test_safety_status_endpoint_returns_payload(test_app):
    response = test_app.get("/api/v1/safety/status")
    assert response.status_code == 200
    payload = response.json()
    assert "kill_switch_level" in payload
    assert "kill_switch_label" in payload
    assert "execution_enabled" in payload
    assert "execution_blocked_reason" in payload
    assert "can_panic" in payload


def test_safety_panic_requires_admin(test_app):
    response = test_app.post("/api/v1/safety/panic")
    assert response.status_code == 403


def test_safety_panic_sets_hard_kill_for_admin(test_app, db, monkeypatch):
    # Ensure the fixture user exists, then elevate for this test.
    test_app.get("/api/v1/safety/status")
    user = get_user_by_email(db, "test@example.com")
    assert user is not None
    prev_super = bool(user.is_superuser)
    prev_level = int(getattr(settings, "safety_kill_switch_level", 0))

    persisted = {}

    def fake_load_config():
        return {"safety_kill_switch_level": 0}

    def fake_save_config(cfg):
        persisted.update(cfg)

    monkeypatch.setattr(app_routes, "_load_config", fake_load_config)
    monkeypatch.setattr(app_routes, "_save_config", fake_save_config)
    monkeypatch.setattr(
        app_routes,
        "_lock_all_tmux_connectors_for_failsafe",
        lambda reason: 4,
    )

    user.is_superuser = True
    db.add(user)
    db.commit()

    try:
        settings.safety_kill_switch_level = 0
        response = test_app.post("/api/v1/safety/panic")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["kill_switch_level"] == 5
        assert payload["can_panic"] is True
        assert payload["locked_connectors"] == 4
        assert persisted["safety_kill_switch_level"] == 5
    finally:
        settings.safety_kill_switch_level = prev_level
        user = get_user_by_email(db, "test@example.com")
        if user is not None:
            user.is_superuser = prev_super
            db.add(user)
            db.commit()
