from app import crud
from app.core.config import settings
from app.schemas.connector import ConnectorCreate


def test_approval_execute_blocked_in_read_only(test_app, db, monkeypatch):
    # Create a connector owned by the test user.
    user = test_app.get("/api/v1/users/me").json()
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux ops", connector_type="tmux", config={"session": "ops"}
        ),
        user_id=user["id"],
    )

    approval = crud.command_approval.create(
        db,
        user_id=user["id"],
        connector_id=int(connector.id),
        event_id=None,
        command_text="ls -la",
        command_class="read",
        reason="test",
        confirm_token="",
    )

    called = {"count": 0}

    class Dummy:
        def send_message(self, payload):
            called["count"] += 1
            return {"status": "sent"}

    # Router imports get_connector directly, patch that symbol.
    import app.api.api_v1.routers.approvals as approvals_mod

    monkeypatch.setattr(approvals_mod, "get_connector", lambda *a, **k: Dummy())

    prev = settings.safety_read_only
    settings.safety_read_only = True
    try:
        resp = test_app.post(
            f"/api/v1/approvals/{approval.id}/approve", json={"reason": "ok"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert called["count"] == 0
    finally:
        settings.safety_read_only = prev


def test_approval_execute_blocked_in_kill_switch_action_hold(test_app, db, monkeypatch):
    user = test_app.get("/api/v1/users/me").json()
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux ops hold", connector_type="tmux", config={"session": "ops"}
        ),
        user_id=user["id"],
    )

    approval = crud.command_approval.create(
        db,
        user_id=user["id"],
        connector_id=int(connector.id),
        event_id=None,
        command_text="ls -la",
        command_class="read",
        reason="test",
        confirm_token="",
    )

    called = {"count": 0}

    class Dummy:
        def send_message(self, payload):
            called["count"] += 1
            return {"status": "sent"}

    import app.api.api_v1.routers.approvals as approvals_mod

    monkeypatch.setattr(approvals_mod, "get_connector", lambda *a, **k: Dummy())

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    settings.safety_kill_switch_level = 1
    try:
        resp = test_app.post(
            f"/api/v1/approvals/{approval.id}/approve", json={"reason": "ok"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert called["count"] == 0
    finally:
        settings.safety_kill_switch_level = prev_level
