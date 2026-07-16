import time
import json
import pathlib
import uuid
from datetime import datetime, timezone

import pytest

from app import crud
from app import models
from app.api.api_v1.routers.tmux import (
    _profile_path,
    _read_session_bootstrap_from_dir,
)
from app.core.config import settings
from app.models import Connector
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate


@pytest.fixture(autouse=True)
def _isolate_tmux_profile_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    profile_root = tmp_path / "tmux_profiles"

    def profile_dir_for_user(user):
        directory = profile_root / str(int(user.id))
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._profile_dir_for_user",
        profile_dir_for_user,
    )


def test_tmux_sessions_endpoint(test_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {
                "session_name": "ops",
                "windows": 2,
                "attached": 1,
                "created": "Tue Feb 17 21:23:04 2026",
            }
        ],
    )

    resp = test_app.get("/api/v1/tmux/sessions")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["items"][0]["session_name"] == "ops"


def test_tmux_panes_endpoint_filters_by_session(test_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {"session_name": "ops", "target": "ops:0.0", "pane_title": "main"},
            {"session_name": "workers", "target": "workers:1.0", "pane_title": "w1"},
        ],
    )

    resp = test_app.get("/api/v1/tmux/panes?session=ops")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["items"][0]["target"] == "ops:0.0"


def test_tmux_capture_endpoint(test_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.tmux_inspector.capture_pane",
        lambda target, lines=200, socket_path="": "hello from pane",
    )

    resp = test_app.get("/api/v1/tmux/capture?target=ops:0.0&lines=25")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["target"] == "ops:0.0"
    assert payload["lines"] == 25
    assert "hello from pane" in payload["text"]


def test_tmux_capture_endpoint_handles_errors(test_app, monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("tmux capture failed")

    monkeypatch.setattr("app.services.tmux_inspector.capture_pane", _raise)

    resp = test_app.get("/api/v1/tmux/capture?target=ops:0.0&lines=25")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "tmux capture failed"


def test_tmux_capture_endpoint_socket_error_has_actionable_detail(
    test_app, monkeypatch
) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError(
            "error connecting to /tmp/tmux-1000/default (No such file or directory)"
        )

    monkeypatch.setattr("app.services.tmux_inspector.capture_pane", _raise)

    resp = test_app.get("/api/v1/tmux/capture?target=ops:0.0&lines=25")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "tmux socket not found" in detail
    assert "socket_path" in detail


def test_tmux_send_endpoint_sends_command(test_app, db, monkeypatch) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-main",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    sent = {}

    class DummyTmux:
        def send_message(self, message):
            sent["message"] = message
            return {"status": "sent", "target": "norman:0.0"}

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "sent"
    assert payload["target"] == "norman:0.0"
    assert sent["message"]["command"] == "status"
    assert sent["message"]["enter_count"] == 2


def test_tmux_send_endpoint_socket_error_has_actionable_detail(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-socket-error",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    class DummyTmux:
        def send_message(self, message):
            raise RuntimeError(
                "error connecting to /tmp/tmux-1000/default (No such file or directory)"
            )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "tmux socket not found" in detail
    assert "socket_path" in detail


def test_tmux_send_endpoint_supports_custom_enter_count(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-custom-enter-count",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    sent = {}

    class DummyTmux:
        def send_message(self, message):
            sent["message"] = message
            return {"status": "sent", "target": "norman:0.0"}

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
            "enter_count": 2,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "sent"
    assert payload["target"] == "norman:0.0"
    assert sent["message"]["command"] == "status"
    assert sent["message"]["enter_count"] == 2


def test_tmux_control_audit_endpoint_returns_centralized_events(test_app, db) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-keystone",
            connector_type="tmux",
            config={"session": "keystone-codex", "target": "keystone-codex:0.0"},
        ),
        user_id=user.id,
    )
    event = models.ConsoleAuditEvent(
        user_id=user.id,
        connector_id=connector.id,
        connector_name=connector.name,
        session_name="keystone-codex",
        agent_name="Keystone",
        host_name="private-host",
        source_event_id=str(uuid.uuid4()),
        event_type="chat.completed",
        severity="info",
        actor_type="bot",
        summary="Web prompt completed.",
        detail="Completed a turn.",
        payload_json={"speed": "balanced"},
        event_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()

    resp = test_app.get("/api/v1/tmux/control/audit")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] >= 1
    assert any(
        item["connector_id"] == connector.id
        and item["event_type"] == "chat.completed"
        and item["session_name"] == "keystone-codex"
        for item in payload["items"]
    )


def test_tmux_control_credits_endpoint_returns_monitor_summary(
    test_app, db, monkeypatch
) -> None:
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

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-mls",
            connector_type="tmux",
            config={
                "session": "mls-codex",
                "target": "mls-codex:0.0",
                "web_url": "https://mlsbot.home.arpa/",
            },
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {
                "session_name": "mls-codex",
                "windows": 1,
                "attached": 0,
                "created": "Thu Apr 2 10:00:00 2026",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {
                "session_name": "mls-codex",
                "target": "mls-codex:0.0",
                "pane_current_command": "codex",
                "pane_current_path": "/tmp",
            }
        ],
    )

    class Snapshot:
        connector_id = connector.id
        connector_name = "tmux-mls"
        web_url = "https://mlsbot.home.arpa/"
        issue_code = "needs_billing"
        issue_label = "Needs billing"
        issue_summary = "Usage limit reached."
        billing_url = (
            "https://platform.openai.com/settings/organization/billing/overview"
        )
        limits_url = "https://platform.openai.com/settings/organization/limits"
        chat_model = "gpt-5.4"
        default_speed = "fast"
        recommended_speed = "balanced"
        recommended_speed_reason = "Fast is enabled while idle."
        auth_required = False
        auth_mode = ""
        reachable = True
        checked_at = 1234567890.0
        usage_tracked = True
        usage_window_seconds = 86400
        usage_turns = 12
        usage_successful_turns = 11
        usage_failed_turns = 1
        usage_input_tokens = 4200
        usage_cached_input_tokens = 900
        usage_output_tokens = 380
        usage_total_tokens = 4580
        usage_window_turns = 5
        usage_window_input_tokens = 1800
        usage_window_cached_input_tokens = 450
        usage_window_output_tokens = 160
        usage_window_total_tokens = 1960
        usage_last_turn_at = 1234567890
        usage_last_turn_total_tokens = 220
        codex_subscription_capacity_state = "available"
        codex_subscription_capacity_fresh = True
        codex_subscription_capacity_observed_at = 1234567800
        codex_subscription_capacity_percent_left = 84
        codex_subscription_capacity_reset_hint = "2h 10m"
        codex_subscription_capacity_eligible = True
        codex_subscription_capacity_tokens_per_hour = 4321
        codex_subscription_capacity_projected_tokens_to_reset = 9362

    async def _items(connector_ids=None):
        return [Snapshot()]

    async def _summary(connector_ids=None):
        return {
            "count": 1,
            "needs_billing": 1,
            "needs_reauth": 0,
            "downgrade_candidates": 1,
            "reachable": 1,
            "checked": 1,
            "usage_tracked": 1,
            "usage_turns": 12,
            "usage_input_tokens": 4200,
            "usage_cached_input_tokens": 900,
            "usage_output_tokens": 380,
            "usage_total_tokens": 4580,
            "usage_window_turns": 5,
            "usage_window_input_tokens": 1800,
            "usage_window_cached_input_tokens": 450,
            "usage_window_output_tokens": 160,
            "usage_window_total_tokens": 1960,
            "usage_last_turn_at": 1234567890,
            "codex_subscription_capacity_available": 1,
            "codex_subscription_capacity_eligible": 1,
        }

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.fleet_credit_monitor.get_items", _items
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.fleet_credit_monitor.get_summary", _summary
    )

    resp = test_app.get("/api/v1/tmux/control/credits")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["needs_billing"] == 1
    assert payload["downgrade_candidates"] == 1
    assert payload["items"][0]["issue_code"] == "needs_billing"
    assert payload["items"][0]["recommended_speed"] == "balanced"
    assert payload["usage_tracked"] == 1
    assert payload["usage_window_total_tokens"] == 1960
    assert payload["items"][0]["usage_total_tokens"] == 4580
    assert payload["items"][0]["usage_window_turns"] == 5
    assert payload["codex_subscription_capacity_available"] == 1
    assert payload["items"][0]["codex_subscription_capacity_percent_left"] == 84
    assert payload["items"][0]["codex_subscription_capacity_eligible"] is True


def test_tmux_send_endpoint_blocks_locked_connector(test_app, db, monkeypatch) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-locked",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0", "locked": True},
        ),
        user_id=user.id,
    )

    class DummyTmux:
        def send_message(self, message):
            raise AssertionError("send_message should not be called for locked session")

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "blocked"
    assert "locked" in payload["reason"].lower()


def test_tmux_send_endpoint_blocked_by_kill_switch_command_hold(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-kill-switch",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    class DummyTmux:
        def send_message(self, message):
            raise AssertionError("send_message should not be called")

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    settings.safety_kill_switch_level = 2
    try:
        resp = test_app.post(
            "/api/v1/tmux/send",
            json={
                "connector_id": connector.id,
                "text": "status",
                "target": "norman:0.0",
            },
        )
    finally:
        settings.safety_kill_switch_level = prev_level

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "blocked"
    assert "kill-switch" in payload["reason"].lower()


def test_tmux_send_endpoint_watchdog_autolocks_missing_session(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-watchdog",
            connector_type="tmux",
            config={"session": "norman-watchdog", "target": "norman-watchdog:0.0"},
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._tmux_has_session", lambda *a, **k: False
    )

    class DummyTmux:
        def send_message(self, message):
            raise AssertionError("send_message should not be called")

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    prev_level = getattr(settings, "safety_kill_switch_level", 0)
    prev_watchdog = getattr(settings, "safety_tmux_watchdog_autolock", False)
    settings.safety_kill_switch_level = 0
    settings.safety_tmux_watchdog_autolock = True
    try:
        resp = test_app.post(
            "/api/v1/tmux/send",
            json={
                "connector_id": connector.id,
                "text": "status",
                "target": "norman-watchdog:0.0",
            },
        )
    finally:
        settings.safety_kill_switch_level = prev_level
        settings.safety_tmux_watchdog_autolock = prev_watchdog

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "blocked"
    assert "watchdog" in payload["reason"].lower()

    db.expire_all()
    refreshed = crud.connector.get(db, connector.id)
    assert bool((refreshed.config or {}).get("locked")) is True
    assert "session_missing" in str((refreshed.config or {}).get("locked_reason") or "")


def test_tmux_send_endpoint_requires_approval_for_risky_command(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-risky",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    class DummyTmux:
        def send_message(self, message):
            raise AssertionError("send_message should not be called")

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "rm -rf /tmp/nope",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "needs_approval"
    assert payload["approval_id"] is not None
    assert payload["confirm_token"]


def test_tmux_send_endpoint_times_out_when_backend_hangs(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-timeout",
            connector_type="tmux",
            config={"session": "norman", "target": "norman:0.0"},
        ),
        user_id=user.id,
    )

    class DummyTmux:
        def send_message(self, message):
            time.sleep(1.5)
            return {"status": "sent", "target": "norman:0.0"}

    class DummySettings:
        safety_default_tmux_mode = "chat"
        safety_execution_enabled = True
        safety_read_only = False
        safety_tmux_send_timeout_seconds = 1

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_settings",
        lambda: DummySettings(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 504
    assert "timed out" in resp.json().get("detail", "").lower()


def test_tmux_control_sessions_endpoint_marks_managed_and_protected(
    test_app, db, monkeypatch
) -> None:
    session_name = f"ops-web-{uuid.uuid4().hex[:8]}"
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

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name=f"tmux:{session_name}",
            connector_type="tmux",
            config={
                "session": session_name,
                "target": f"{session_name}:0.0",
                "web_url": "http://127.0.0.1:8788",
            },
        ),
        user_id=user.id,
    )
    assert connector.id

    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {"session_name": session_name, "windows": 1, "attached": 0},
            {"session_name": "operator", "windows": 1, "attached": 1},
        ],
    )
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {
                "session_name": session_name,
                "window_index": 0,
                "pane_index": 0,
                "target": f"{session_name}:0.0",
                "pane_current_command": "node",
                "pane_current_path": "/tmp/ops",
            },
            {
                "session_name": "operator",
                "window_index": 0,
                "pane_index": 0,
                "target": "operator:0.0",
                "pane_current_command": "node",
                "pane_current_path": "/tmp/operator",
            },
        ],
    )

    resp = test_app.get("/api/v1/tmux/control/sessions")
    assert resp.status_code == 200
    payload = resp.json()
    by_name = {item["session_name"]: item for item in payload["items"]}
    assert by_name[session_name]["managed"] is True
    assert by_name[session_name]["connector_id"] is not None
    assert str(by_name[session_name]["connector_name"]).strip() != ""
    assert by_name[session_name]["locked"] is False
    assert by_name[session_name]["operator_mode"] == "observe"
    assert by_name[session_name]["web_url"] == "http://127.0.0.1:8788"
    assert by_name["operator"]["protected"] is True


def test_tmux_control_sessions_endpoint_includes_remote_auth_state(
    test_app, db, monkeypatch
) -> None:
    session_name = f"ops-auth-{uuid.uuid4().hex[:8]}"
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

    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name=f"tmux:{session_name}",
            connector_type="tmux",
            config={
                "session": session_name,
                "target": f"{session_name}:0.0",
                "web_url": "http://127.0.0.1:8799?token=test",
            },
        ),
        user_id=user.id,
    )
    assert connector.id

    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {"session_name": session_name, "windows": 1, "attached": 0},
        ],
    )
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {
                "session_name": session_name,
                "window_index": 0,
                "pane_index": 0,
                "target": f"{session_name}:0.0",
                "pane_current_command": "codex",
                "pane_current_path": "/tmp/auth",
            }
        ],
    )

    async def fake_status_map(web_urls):
        return {
            "http://127.0.0.1:8799?token=test": {
                "reachable": True,
                "status_message": "Needs reauth",
                "auth_required": True,
                "auth_mode": "device_code",
                "auth_summary": "Finish sign-in with a device code.",
                "auth_verification_url": "https://auth.openai.com/codex/device",
                "auth_device_code": "ABCD-1234",
            }
        }

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.fetch_console_status_map",
        fake_status_map,
    )

    resp = test_app.get("/api/v1/tmux/control/sessions")
    assert resp.status_code == 200
    payload = resp.json()
    item = next(row for row in payload["items"] if row["session_name"] == session_name)
    assert item["status_available"] is True
    assert item["auth_required"] is True
    assert item["auth_mode"] == "device_code"
    assert item["auth_verification_url"] == "https://auth.openai.com/codex/device"
    assert item["auth_device_code"] == "ABCD-1234"


def test_tmux_control_adopt_creates_connector_channel_and_bot(
    test_app, db, monkeypatch, tmp_path
) -> None:
    workdir = tmp_path / "castle-lite"
    workdir.mkdir()
    expected_bootstrap = "codex resume 019c-test-castle"
    (workdir / ".session").write_text(expected_bootstrap + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {"session_name": "castle-lite", "windows": 1, "attached": 0}
        ],
    )
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {
                "session_name": "castle-lite",
                "window_index": 0,
                "pane_index": 0,
                "target": "castle-lite:0.0",
                "pane_current_command": "bash",
                "pane_current_path": str(workdir),
            }
        ],
    )

    resp = test_app.post(
        "/api/v1/tmux/control/adopt",
        json={
            "session": "castle-lite",
            "create_channel": True,
            "create_bot": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "adopted"
    assert payload["session"] == "castle-lite"
    assert payload["channel_id"] is not None
    assert payload["bot_id"] is not None

    connector = crud.connector.get(db, payload["connector_id"])
    assert connector is not None
    assert connector.connector_type == "tmux"
    assert connector.config["session"] == "castle-lite"
    assert connector.config["working_dir"] == str(workdir)
    assert connector.config["session_bootstrap"] == expected_bootstrap


def test_tmux_control_stop_protected_requires_force(test_app) -> None:
    resp = test_app.post("/api/v1/tmux/control/stop", json={"session": "operator"})
    assert resp.status_code == 403
    assert "protected" in resp.json().get("detail", "").lower()


def test_tmux_control_start_uses_connector_bootstrap(test_app, db, monkeypatch) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops",
            connector_type="tmux",
            config={
                "session": "ops",
                "target": "ops:0.0",
                "working_dir": "/tmp/ops",
                "session_bootstrap": "codex resume 019c-control-test",
            },
        ),
        user_id=user.id,
    )

    calls = []
    state = {"has_session": False}

    class DummyProc:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_tmux(*args, socket_path="", check=False):
        calls.append(tuple(args))
        if args[0] == "has-session":
            return DummyProc(returncode=0 if state["has_session"] else 1)
        if args[0] == "new-session":
            state["has_session"] = True
            return DummyProc(returncode=0)
        if args[0] == "display-message" and args[-1] == "#{pane_id}":
            return DummyProc(returncode=0, stdout="%1\n")
        if args[0] == "send-keys":
            return DummyProc(returncode=0)
        return DummyProc(returncode=0)

    monkeypatch.setattr("app.api.api_v1.routers.tmux._run_tmux", fake_run_tmux)
    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._pane_child_command",
        lambda target, socket_path="": "",
    )

    resp = test_app.post(
        "/api/v1/tmux/control/start",
        json={"connector_id": connector.id},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["started_session"] is True
    assert payload["launched_command"] is True
    assert any(call[:4] == ("send-keys", "-t", "ops:0.0", "-l") for call in calls)


def test_tmux_control_start_blocked_when_session_locked(test_app, db) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-locked",
            connector_type="tmux",
            config={
                "session": "ops-locked",
                "target": "ops-locked:0.0",
                "locked": True,
            },
        ),
        user_id=user.id,
    )

    resp = test_app.post(
        "/api/v1/tmux/control/start",
        json={"connector_id": connector.id},
    )
    assert resp.status_code == 423
    assert "locked" in resp.json().get("detail", "").lower()


def test_tmux_control_lock_endpoint_updates_connector(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-lockable",
            connector_type="tmux",
            config={"session": "ops-lockable", "target": "ops-lockable:0.0"},
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._tmux_has_session", lambda *args, **kwargs: False
    )

    lock_resp = test_app.post(
        "/api/v1/tmux/control/lock",
        json={"connector_id": connector.id, "locked": True},
    )
    assert lock_resp.status_code == 200
    payload = lock_resp.json()
    assert payload["status"] == "ok"
    assert payload["locked"] is True
    assert payload["detail"] == "locked"

    db.expire_all()
    refreshed = crud.connector.get(db, connector.id)
    assert bool((refreshed.config or {}).get("locked")) is True

    unlock_resp = test_app.post(
        "/api/v1/tmux/control/lock",
        json={"connector_id": connector.id, "locked": False},
    )
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["locked"] is False
    db.expire_all()
    refreshed = crud.connector.get(db, connector.id)
    assert bool((refreshed.config or {}).get("locked")) is False


def test_tmux_control_operator_endpoint_updates_connector(test_app, db) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-operator",
            connector_type="tmux",
            config={"session": "ops-operator", "target": "ops-operator:0.0"},
        ),
        user_id=user.id,
    )

    resp = test_app.post(
        "/api/v1/tmux/control/operator",
        json={
            "connector_id": connector.id,
            "mode": "take",
            "note": "manual takeover",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["operator_mode"] == "take"
    assert payload["operator_note"] == "manual takeover"

    db.expire_all()
    refreshed = crud.connector.get(db, connector.id)
    assert (refreshed.config or {}).get("operator_mode") == "take"
    assert (refreshed.config or {}).get("operator_note") == "manual takeover"


def test_tmux_control_web_url_endpoint_updates_connector(test_app, db) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-web",
            connector_type="tmux",
            config={"session": "ops-web", "target": "ops-web:0.0"},
        ),
        user_id=user.id,
    )

    resp = test_app.post(
        "/api/v1/tmux/control/web-url",
        json={
            "connector_id": connector.id,
            "web_url": "192.168.2.137:8788",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["web_url"] == "http://192.168.2.137:8788"

    db.expire_all()
    refreshed = crud.connector.get(db, connector.id)
    assert (refreshed.config or {}).get("web_url") == "http://192.168.2.137:8788"

    clear_resp = test_app.post(
        "/api/v1/tmux/control/web-url",
        json={
            "connector_id": connector.id,
            "web_url": "",
        },
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["web_url"] == ""


def test_tmux_control_auth_device_relays_remote_console_action(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-auth-device",
            connector_type="tmux",
            config={
                "session": "ops-auth-device",
                "target": "ops-auth-device:0.0",
                "web_url": "http://127.0.0.1:8799?token=test",
            },
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._post_console_action",
        lambda web_url, action_path, timeout=8.0: {
            "detail": "Device-code sign-in is ready.",
            "snapshot": {
                "auth": {
                    "required": True,
                    "mode": "device_code",
                    "summary": "Complete device-code sign-in in your browser.",
                    "verification_url": "https://auth.openai.com/codex/device",
                    "device_code": "VAQW-77M8G",
                }
            },
        },
    )

    resp = test_app.post(
        "/api/v1/tmux/control/auth-device",
        json={"connector_id": connector.id},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["auth_required"] is True
    assert payload["auth_mode"] == "device_code"
    assert payload["auth_verification_url"] == "https://auth.openai.com/codex/device"
    assert payload["auth_device_code"] == "VAQW-77M8G"


def test_tmux_control_auth_browser_relays_remote_console_action(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops-auth-browser",
            connector_type="tmux",
            config={
                "session": "ops-auth-browser",
                "target": "ops-auth-browser:0.0",
                "web_url": "http://127.0.0.1:8799?token=test",
            },
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._post_console_action",
        lambda web_url, action_path, timeout=8.0: {
            "detail": "Browser sign-in is ready.",
            "snapshot": {
                "auth": {
                    "required": True,
                    "mode": "browser_signin",
                    "summary": "Finish browser sign-in in a real browser tab.",
                    "verification_url": "https://auth.openai.com/oauth/authorize?foo=bar",
                    "device_code": "",
                }
            },
        },
    )

    resp = test_app.post(
        "/api/v1/tmux/control/auth-browser",
        json={"connector_id": connector.id},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["auth_required"] is True
    assert payload["auth_mode"] == "browser_signin"
    assert (
        payload["auth_verification_url"]
        == "https://auth.openai.com/oauth/authorize?foo=bar"
    )
    assert payload["auth_device_code"] == ""


def test_tmux_send_endpoint_allows_manual_send_during_operator_takeover(
    test_app, db, monkeypatch
) -> None:
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
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux-manual-takeover",
            connector_type="tmux",
            config={
                "session": "norman",
                "target": "norman:0.0",
                "operator_mode": "take",
                "operator_note": "manual takeover",
            },
        ),
        user_id=user.id,
    )

    sent = {}

    class DummyTmux:
        def send_message(self, message):
            sent["message"] = message
            return {"status": "sent", "target": "norman:0.0"}

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux.get_connector",
        lambda connector_type, config: DummyTmux(),
    )

    resp = test_app.post(
        "/api/v1/tmux/send",
        json={
            "connector_id": connector.id,
            "text": "status",
            "target": "norman:0.0",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    assert sent["message"]["command"] == "status"


def test_tmux_control_lock_all_endpoint_locks_user_tmux_connectors(
    test_app, db, monkeypatch
) -> None:
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
    first = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:first",
            connector_type="tmux",
            config={"session": "first", "target": "first:0.0"},
        ),
        user_id=user.id,
    )
    second = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:second",
            connector_type="tmux",
            config={"session": "second", "target": "second:0.0"},
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.tmux._tmux_has_session", lambda *args, **kwargs: False
    )

    resp = test_app.post(
        "/api/v1/tmux/control/lock-all",
        json={"locked": True, "stop_sessions": False},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["locked"] is True
    assert payload["updated"] >= 2

    db.expire_all()
    first_refreshed = crud.connector.get(db, first.id)
    second_refreshed = crud.connector.get(db, second.id)
    assert bool((first_refreshed.config or {}).get("locked")) is True
    assert bool((second_refreshed.config or {}).get("locked")) is True


def test_tmux_profile_save_and_load(test_app, db, monkeypatch, tmp_path) -> None:
    session_name = f"profile-web-{uuid.uuid4().hex[:8]}"
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
    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name=f"tmux:{session_name}",
            connector_type="tmux",
            config={
                "session": session_name,
                "target": f"{session_name}:0.0",
                "working_dir": "/tmp/ops",
                "session_bootstrap": "codex resume 019c-profile-test",
                "web_url": "http://127.0.0.1:8788",
            },
        ),
        user_id=user.id,
    )

    save_resp = test_app.post(
        "/api/v1/tmux/control/profiles/save", json={"name": "default_pack"}
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "saved"
    profile_path = _profile_path(user, "default_pack")
    assert profile_path.is_relative_to(tmp_path)
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    saved_item = next(
        item for item in saved["items"] if item.get("session") == session_name
    )
    assert saved_item["web_url"] == "http://127.0.0.1:8788"

    profile_list = test_app.get("/api/v1/tmux/control/profiles")
    assert profile_list.status_code == 200
    assert any(item["name"] == "default_pack" for item in profile_list.json()["items"])

    # Load without starting tmux sessions so no tmux process is required in tests.
    load_resp = test_app.post(
        "/api/v1/tmux/control/profiles/load",
        json={"name": "default_pack", "start_sessions": False},
    )
    assert load_resp.status_code == 200
    assert load_resp.json()["status"] == "loaded"
    assert load_resp.json()["sessions"] >= 1
    connector = (
        db.query(Connector)
        .filter(
            Connector.user_id == user.id,
            Connector.name == f"tmux:{session_name}",
        )
        .first()
    )
    assert connector is not None
    assert (connector.config or {}).get("web_url") == "http://127.0.0.1:8788"


def test_tmux_profile_save_running_only_snapshots_live_sessions(
    test_app, db, monkeypatch, tmp_path
) -> None:
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

    live_dir = tmp_path / "live-session"
    live_dir.mkdir()
    (live_dir / ".session").write_text(
        "codex resume 019c-live-profile\n", encoding="utf-8"
    )

    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:live-managed",
            connector_type="tmux",
            config={
                "session": "live-managed",
                "target": "live-managed:0.0",
                "working_dir": "/tmp/managed",
                "session_bootstrap": "codex resume 019c-managed-profile",
                "web_url": "http://127.0.0.1:8701",
            },
        ),
        user_id=user.id,
    )
    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:offline-stale",
            connector_type="tmux",
            config={
                "session": "offline-stale",
                "target": "offline-stale:0.0",
                "working_dir": "/tmp/offline",
            },
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.services.tmux_inspector.list_sessions",
        lambda socket_path="": [
            {
                "session_name": "live-managed",
                "windows": 1,
                "attached": 0,
                "created": "Thu Mar 05 10:00:00 2026",
            },
            {
                "session_name": "live-unmanaged",
                "windows": 1,
                "attached": 0,
                "created": "Thu Mar 05 10:01:00 2026",
            },
        ],
    )
    monkeypatch.setattr(
        "app.services.tmux_inspector.list_panes",
        lambda socket_path="": [
            {
                "session_name": "live-managed",
                "target": "live-managed:0.0",
                "pane_current_path": "/tmp/managed-live",
            },
            {
                "session_name": "live-unmanaged",
                "target": "live-unmanaged:0.0",
                "pane_current_path": str(live_dir),
            },
        ],
    )

    save_resp = test_app.post(
        "/api/v1/tmux/control/profiles/save",
        json={
            "name": "running_now",
            "running_only": True,
            "include_protected": True,
        },
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "saved"
    assert save_resp.json()["sessions"] == 2

    profile_path = _profile_path(user, "running_now")
    assert profile_path.is_relative_to(tmp_path)
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved["snapshot_mode"] == "running"

    items = {item["session"]: item for item in saved["items"]}
    assert set(items) == {"live-managed", "live-unmanaged"}
    assert items["live-managed"]["web_url"] == "http://127.0.0.1:8701"
    assert (
        items["live-managed"]["session_bootstrap"]
        == "codex resume 019c-managed-profile"
    )
    assert (
        items["live-unmanaged"]["session_bootstrap"] == "codex resume 019c-live-profile"
    )


def test_read_session_bootstrap_ignores_empty_working_dir(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".session").write_text(
        "codex resume 019c-bootstrap-should-not-load\n", encoding="utf-8"
    )

    assert _read_session_bootstrap_from_dir("") == ""


def test_tmux_profile_rename_and_delete(test_app, db) -> None:
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
    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:ops",
            connector_type="tmux",
            config={
                "session": "ops",
                "target": "ops:0.0",
                "working_dir": "/tmp/ops",
                "session_bootstrap": "codex resume 019c-profile-rename",
            },
        ),
        user_id=user.id,
    )

    suffix = uuid.uuid4().hex[:8]
    original_name = f"layout_{suffix}"
    renamed_name = f"layout_{suffix}_renamed"

    save_resp = test_app.post(
        "/api/v1/tmux/control/profiles/save", json={"name": original_name}
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "saved"

    rename_resp = test_app.post(
        "/api/v1/tmux/control/profiles/rename",
        json={"from_name": original_name, "to_name": renamed_name},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["status"] == "renamed"
    assert rename_resp.json()["name"] == renamed_name

    profile_list = test_app.get("/api/v1/tmux/control/profiles")
    assert profile_list.status_code == 200
    names = {item["name"] for item in profile_list.json()["items"]}
    assert renamed_name in names
    assert original_name not in names

    delete_resp = test_app.delete(f"/api/v1/tmux/control/profiles/{renamed_name}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"
    assert delete_resp.json()["name"] == renamed_name
