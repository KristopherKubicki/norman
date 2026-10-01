"""Exact mobile retries acknowledge durable work without repeating admission."""

import ast
from pathlib import Path

import pytest

SOURCES = [
    Path("scripts/norman_codex_web.py"),
    Path("scripts/agent_console_template/agent_console_web.py"),
]


def load_functions(path, names, scope):
    nodes = [
        n
        for n in ast.parse(path.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    exec(
        compile(
            ast.Module(
                body=[
                    ast.parse("from __future__ import annotations").body[0],
                    *nodes,
                ],
                type_ignores=[],
            ),
            str(path),
            "exec",
        ),
        scope,
    )


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("queued", [False, True])
def test_recorded_retry_skips_admission_without_mutating_state(path, queued):
    item = {
        "submission_id": "request-123",
        "source": "operator",
        "prompt": "check HAL",
        "attachments": [],
    }
    meta = {
        "pending": not queued,
        "running_submission_id": "request-123",
        "running_request_source": "operator",
        "running_prompt": "check HAL",
        "running_attachments": [],
        "queued_prompts": [item] if queued else [],
    }
    original = repr(meta)
    scope = {
        "STATUS_LOCK": None,  # Fast reads must not wait for the worker lock.
        "load_status_meta": lambda: meta,
        "normalize_submission_id": lambda v: v or "",
        "normalize_attachments": lambda v: v or [],
        "prompt_attachment_signature": lambda v: repr(v or []),
        "normalize_queue": lambda v: v or [],
        "_live_status_overlay": lambda: {"pending": True},
    }

    def admission():
        raise AssertionError("retry must not repeat admission")

    scope["host_pressure_guard_snapshot"] = admission
    load_functions(path, {"recorded_operator_submission", "start_web_prompt"}, scope)
    accepted, result = scope["start_web_prompt"](
        "check HAL", "normal", 2, source="operator", submission_id="request-123"
    )
    assert accepted and result["deduplicated_prompt"]
    assert result["recorded_submission_state"] == ("queued" if queued else "running")
    assert repr(meta) == original
    check = scope["recorded_operator_submission"]
    assert check("check HAL", [], "") == ("", 0)
    assert check("check HAL", [], "another-id") == ("", 0)
    assert check("different work", [], "request-123") == ("", 0)
    assert check("check HAL", [{"id": "new-file"}], "request-123") == ("", 0)
    if queued:
        item["source"] = "relay"
    else:
        meta["pending"] = False
    assert check("check HAL", [], "request-123") == ("", 0)


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize(
    "source,relay", [("operator", {}), ("relay", {}), ("operator", {"relay_id": "abc"})]
)
def test_unrecorded_or_relay_work_still_enters_admission(path, source, relay):
    class AdmissionReached(Exception):
        pass

    def admission():
        raise AdmissionReached

    scope = {
        "host_pressure_guard_snapshot": admission,
        "recorded_operator_submission": lambda *args: ("", 0),
    }
    load_functions(path, {"start_web_prompt"}, scope)
    with pytest.raises(AdmissionReached):
        scope["start_web_prompt"](
            "new work", "normal", 2, source=source, relay_callback=relay
        )


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("kind", ["command", "status"])
def test_only_matching_shortcuts_probe_runtime(path, kind):
    calls = []
    busy = [False]

    def probe():
        calls.append(True)
        return busy[0]

    scope = {
        "normalize_attachments": lambda v: v or [],
        "prompt_runtime_alive": probe,
        "deterministic_command_request": lambda p: ["pwd"] if p == "shortcut" else None,
        "prompt_core_request": lambda p: p,
        "turn_control_mutation_risk": lambda p: "none",
        "prompt_is_broad_planning_request": lambda p: False,
        "prompt_requests_investigation": lambda p: False,
        "prompt_requests_media_work": lambda p: False,
        "prompt_is_explicit_status_request": lambda p: p == "shortcut",
        "prompt_is_quick_status_request": lambda p: p == "shortcut",
        "route_receipt_requested_action": lambda p: "status",
        "re": __import__("re"),
    }
    name = f"deterministic_{kind}_prompt_allowed"
    load_functions(path, {name}, scope)
    fn = scope[name]
    assert not fn("ordinary message", [])
    assert calls == []
    assert fn("shortcut", [])
    busy[0] = True
    assert not fn("shortcut", [])
    assert len(calls) == 2
