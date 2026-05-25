from __future__ import annotations

import pathlib

from app.services import screen_hypervisor


def _registry(tmp_path: pathlib.Path) -> dict:
    return {
        "apps": {
            "demo": {
                "app": {
                    "screen": "app-demo",
                    "cwd": str(tmp_path),
                    "command": "python app.py",
                    "log_file": str(tmp_path / "app.log"),
                },
                "agent": {
                    "screen": "agent-demo",
                    "cwd": str(tmp_path),
                    "command": "codex --no-alt-screen resume 123",
                    "log_file": str(tmp_path / "agent.log"),
                },
            }
        }
    }


def test_send_queues_when_target_locked(tmp_path):
    registry = _registry(tmp_path)
    state_dir = tmp_path / "state"
    screen_hypervisor.save_state(
        "demo",
        "agent",
        {"locked": True, "inflight": False, "log_offset": 0},
        state_dir=state_dir,
    )

    result = screen_hypervisor.send(
        registry,
        "demo",
        text="hello",
        target="agent",
        enter_count=2,
        state_dir=state_dir,
    )

    assert result["status"] == "queued"
    assert result["reason"] == "locked"
    assert screen_hypervisor.queue_length("demo", "agent", state_dir=state_dir) == 1


def test_send_dispatch_sets_inflight(tmp_path, monkeypatch):
    registry = _registry(tmp_path)
    state_dir = tmp_path / "state"
    calls = []

    monkeypatch.setattr(screen_hypervisor, "_session_exists", lambda session: True)
    monkeypatch.setattr(
        screen_hypervisor,
        "_dispatch_to_session",
        lambda session, text, enter_count: calls.append((session, text, enter_count)),
    )

    result = screen_hypervisor.send(
        registry,
        "demo",
        text="ping",
        target="agent",
        enter_count=2,
        state_dir=state_dir,
    )
    state = screen_hypervisor.load_state("demo", "agent", state_dir=state_dir)

    assert result["status"] == "sent"
    assert calls == [("agent-demo", "ping", 2)]
    assert bool(state["inflight"]) is True


def test_pull_logs_auto_ack_and_drain(tmp_path, monkeypatch):
    registry = _registry(tmp_path)
    state_dir = tmp_path / "state"
    agent_log = tmp_path / "agent.log"
    agent_log.write_text("first line\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(screen_hypervisor, "_session_exists", lambda session: True)
    monkeypatch.setattr(
        screen_hypervisor,
        "_dispatch_to_session",
        lambda session, text, enter_count: calls.append((session, text, enter_count)),
    )

    screen_hypervisor.save_state(
        "demo",
        "agent",
        {"locked": False, "inflight": True, "log_offset": 0},
        state_dir=state_dir,
    )
    screen_hypervisor._append_queue(
        "demo",
        "agent",
        text="queued message",
        enter_count=2,
        state_dir=state_dir,
    )

    result = screen_hypervisor.pull_logs(
        registry,
        "demo",
        target="agent",
        state_dir=state_dir,
        max_bytes=4096,
        auto_ack=True,
    )

    assert result["acked"] is True
    assert result["drain"]["status"] == "drained"
    assert calls == [("agent-demo", "queued message", 2)]
    assert screen_hypervisor.queue_length("demo", "agent", state_dir=state_dir) == 0


def test_status_reports_running_and_queue(tmp_path, monkeypatch):
    registry = _registry(tmp_path)
    state_dir = tmp_path / "state"
    screen_hypervisor._append_queue(
        "demo",
        "agent",
        text="hello",
        enter_count=2,
        state_dir=state_dir,
    )
    monkeypatch.setattr(
        screen_hypervisor,
        "list_screen_sessions",
        lambda: ["agent-demo"],
    )

    payload = screen_hypervisor.status(
        registry,
        app_name="demo",
        state_dir=state_dir,
        log_dir=tmp_path,
    )

    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["name"] == "demo"
    assert item["targets"]["agent"]["running"] is True
    assert item["targets"]["agent"]["queue_length"] == 1
    assert item["targets"]["app"]["running"] is False
