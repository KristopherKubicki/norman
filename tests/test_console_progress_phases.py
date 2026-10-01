"""Persist preparation progress without reviving an already completed turn."""

import ast
import threading
from pathlib import Path

import pytest

SOURCES = [
    Path("scripts/norman_codex_web.py"),
    Path("scripts/agent_console_template/agent_console_web.py"),
]


@pytest.mark.parametrize("path", SOURCES)
def test_phase_updates_preserve_current_work_and_ignore_completed_turns(path):
    tree = ast.parse(path.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "record_live_turn_phase"
    )
    meta = {
        "pending": True,
        "live_turn": {"started_at": 10, "event_count": 3},
        "running_prompt": "Repair HAL",
    }
    saves = []
    scope = {
        "STATUS_LOCK": threading.Lock(),
        "load_status_meta": lambda: meta,
        "normalize_live_turn": lambda v: dict(v or {}),
        "now_ts": lambda: 30,
        "save_status_meta": lambda v: saves.append(dict(v)),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    update = scope["record_live_turn_phase"]
    update("preparing_context")
    assert meta["live_turn"] == {
        "started_at": 10,
        "event_count": 3,
        "phase": "preparing_context",
        "phase_started_at": 30,
    }
    assert meta["running_prompt"] == "Repair HAL"
    update("unknown")
    meta["pending"] = False
    update("waiting_model")
    assert len(saves) == 1


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("uid", [0, 1000])
def test_web_restart_uses_noninteractive_existing_privileges(path, uid):
    from types import SimpleNamespace

    tree = ast.parse(path.read_text())
    parent = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "schedule_web_only_restart"
    )
    node = next(
        n
        for n in parent.body
        if isinstance(n, ast.FunctionDef) and n.name == "_restart_web_service"
    )
    calls = []
    scope = {
        "time": SimpleNamespace(sleep=lambda _: None),
        "delay_seconds": 0,
        "os": SimpleNamespace(geteuid=lambda: uid),
        "WEB_SERVICE": "theseus-codex-web.service",
        "run": lambda args: calls.append(args) or SimpleNamespace(returncode=0),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    scope["_restart_web_service"]()
    assert calls == [
        (["sudo", "-n"] if uid else [])
        + ["systemctl", "restart", "theseus-codex-web.service"]
    ]


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize(
    "message",
    [
        "invalid_refresh_token",
        "Could not validate your refresh token",
        "Your access token could not be refreshed",
    ],
)
def test_provider_rejected_refresh_is_recognized_by_backend(path, message):
    tree = ast.parse(path.read_text())
    names = {
        "_contains_token_reuse_error",
        "_contains_openai_auth_error",
        "_contains_codex_auth_failure",
    }
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    assert scope["_contains_codex_auth_failure"](message)
    assert not scope["_contains_codex_auth_failure"](
        "Firewall returned 401 Unauthorized"
    )
