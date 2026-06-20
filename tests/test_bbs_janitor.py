from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_bbs_janitor():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "bbs_janitor.py"
    spec = importlib.util.spec_from_file_location("bbs_janitor", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_owner_alias_is_safe_when_target_actor_is_live() -> None:
    module = _load_bbs_janitor()
    threads = [
        {
            "thread_id": "th_old_eyebat",
            "title": "Eyebat task",
            "owner": "eyebat",
            "status": "waiting",
            "priority": "high",
            "last_message_at": "2026-06-02T04:00:00Z",
            "loop": {"state": "owner_offline"},
            "tags": ["system:glimpser"],
        }
    ]

    actions = module.classify_threads(
        threads,
        live_actors={"glimpser"},
        owner_aliases={"eyebat": "glimpser"},
        now=datetime(2026, 6, 2, 4, 30, tzinfo=timezone.utc),
    )

    assert actions == [
        {
            "action": "owner_alias",
            "safety": "safe",
            "reason": (
                "Owner 'eyebat' is an alias/retired actor; canonical live owner "
                "is 'glimpser'."
            ),
            "thread_id": "th_old_eyebat",
            "title": "Eyebat task",
            "owner": "eyebat",
            "status": "waiting",
            "priority": "high",
            "last_message_at": "2026-06-02T04:00:00Z",
            "target_owner": "glimpser",
        }
    ]


def test_classify_parent_with_child_is_review_only() -> None:
    module = _load_bbs_janitor()
    threads = [
        {
            "thread_id": "th_parent",
            "title": "Broad parent",
            "owner": "netops",
            "status": "open",
            "priority": "high",
            "last_message_at": "2026-06-01T04:00:00Z",
            "loop": {"state": "picked_up"},
            "tags": ["work:implementation"],
        },
        {
            "thread_id": "th_child",
            "title": "Finite child",
            "owner": "netops",
            "status": "open",
            "priority": "high",
            "last_message_at": "",
            "loop": {"state": "waiting_pickup"},
            "message_count": 0,
            "tags": ["work:task", "parent:th_parent"],
        },
    ]

    actions = module.classify_threads(
        threads,
        live_actors={"netops"},
        owner_aliases={},
        now=datetime(2026, 6, 2, 4, 30, tzinfo=timezone.utc),
    )

    parent_actions = [
        action for action in actions if action["thread_id"] == "th_parent"
    ]
    child_actions = [action for action in actions if action["thread_id"] == "th_child"]

    assert parent_actions == [
        {
            "action": "broad_parent_has_child",
            "safety": "review",
            "reason": (
                "Thread has at least one finite child task. Review whether "
                "the parent should be closed as reference/superseded."
            ),
            "thread_id": "th_parent",
            "title": "Broad parent",
            "owner": "netops",
            "status": "open",
            "priority": "high",
            "last_message_at": "2026-06-01T04:00:00Z",
        }
    ]
    assert child_actions == [
        {
            "action": "empty_task_waiting_pickup",
            "safety": "review",
            "reason": (
                "Finite task has no messages yet. Review whether the owner "
                "should ack pickup or the creator should add context."
            ),
            "thread_id": "th_child",
            "title": "Finite child",
            "owner": "netops",
            "status": "open",
            "priority": "high",
            "last_message_at": "",
        }
    ]


def test_classify_unacked_live_owner_handoff_after_sla() -> None:
    module = _load_bbs_janitor()
    threads = [
        {
            "thread_id": "th_waiting",
            "title": "Panelbot upload handoff",
            "owner": "panelbot",
            "status": "open",
            "priority": "high",
            "last_message_at": "2026-06-02T04:00:00Z",
            "loop": {"state": "waiting_pickup"},
            "message_count": 2,
            "tags": ["work:task"],
        }
    ]

    actions = module.classify_threads(
        threads,
        live_actors={"panelbot"},
        owner_aliases={},
        now=datetime(2026, 6, 2, 4, 20, tzinfo=timezone.utc),
        ack_sla_seconds=900,
    )

    assert actions == [
        {
            "action": "unacked_handoff",
            "safety": "review",
            "reason": (
                "Owner TUI 'panelbot' is live but has not ACKed pickup "
                "for 20.0 minutes. Next step: the owner ACKs only if "
                "picking up; otherwise a coordinator should fork, reassign, "
                "mark BLOCKED, or close DONE. Observers should not ACK just "
                "to clear the alert."
            ),
            "thread_id": "th_waiting",
            "title": "Panelbot upload handoff",
            "owner": "panelbot",
            "status": "open",
            "priority": "high",
            "last_message_at": "2026-06-02T04:00:00Z",
            "age_seconds": 1200,
            "ack_sla_seconds": 900,
        }
    ]


def test_apply_safe_actions_posts_only_safe_owner_alias(monkeypatch) -> None:
    module = _load_bbs_janitor()
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="norman",
    )
    actions = [
        {
            "action": "owner_alias",
            "safety": "safe",
            "thread_id": "th_old_eyebat",
            "target_owner": "glimpser",
            "reason": "Owner alias cleanup.",
        },
        {
            "action": "broad_parent_has_child",
            "safety": "review",
            "thread_id": "th_parent",
            "reason": "Needs review.",
        },
    ]

    results = module.apply_safe_actions(args, actions)

    assert calls == [
        (
            "POST",
            "http://bbs.local/api/v1/threads/th_old_eyebat/owner",
            {
                "owner": "glimpser",
                "posted_by": "norman",
                "reason": "Owner alias cleanup.",
            },
        )
    ]
    assert results[0]["ok"] is True
    assert results[0]["thread_id"] == "th_old_eyebat"


def test_live_actors_from_bots_omits_deprecated_and_unhealthy() -> None:
    module = _load_bbs_janitor()
    payload = {
        "ok": True,
        "bots": [
            {
                "actor": "glimpser",
                "directory_status": "live",
                "heartbeat_required": True,
                "heartbeat_ok": True,
                "token_present": True,
            },
            {
                "actor": "publisher",
                "directory_status": "deprecated",
                "heartbeat_required": False,
                "heartbeat_ok": False,
                "token_present": False,
            },
            {
                "actor": "offline",
                "directory_status": "live",
                "heartbeat_required": True,
                "heartbeat_ok": False,
                "token_present": True,
            },
        ],
    }

    assert module.live_actors_from_bots(payload) == {"glimpser"}


def test_parser_defaults_to_norman_bbs_env_file(monkeypatch) -> None:
    monkeypatch.delenv("SWITCHBOARD_ENV_FILE", raising=False)
    monkeypatch.setenv("NORMAN_CODEX_BBS_ENV_FILE", "/etc/panelbot/switchboard-bbs.env")
    module = _load_bbs_janitor()

    args = module.build_parser().parse_args([])

    assert args.env_file == "/etc/panelbot/switchboard-bbs.env"
