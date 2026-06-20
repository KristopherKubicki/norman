from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_bbs_task_lifecycle():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "bbs_task_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("bbs_task_lifecycle", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_fork_payload_inherits_parent_scope_and_links_parent() -> None:
    module = _load_bbs_task_lifecycle()
    args = argparse.Namespace(
        parent_thread_id="th_parent_context",
        thread_id="th_child_task",
        title="Fix the resolver probe",
        owner="netops",
        summary="Concrete resolver follow-up.",
        summary_file=None,
        priority=None,
        site=None,
        system=None,
        topic="resolver-follow-up",
        lane=None,
        tag=["domain:dns"],
        watcher=["norman"],
    )
    parent = {
        "thread_id": "th_parent_context",
        "title": "Headscale parent context",
        "priority": "urgent",
        "scope": {
            "site": "home",
            "system": "headscale",
            "topic": "resolver-plane",
            "lane": "fleet",
        },
    }

    payload = module.build_fork_payload(parent=parent, args=args, actor="norman")

    assert payload["thread_id"] == "th_child_task"
    assert payload["priority"] == "urgent"
    assert payload["scope"] == {
        "site": "home",
        "system": "headscale",
        "topic": "resolver-follow-up",
        "lane": "fleet",
    }
    assert payload["created_by"] == "norman"
    assert payload["owner"] == "netops"
    assert payload["watchers"] == ["norman"]
    assert "work:task" in payload["tags"]
    assert "parent:th_parent_context" in payload["tags"]
    assert "Parent BBS thread: th_parent_context" in payload["summary"]


def test_ack_posts_to_existing_bbs_ack_endpoint(monkeypatch) -> None:
    module = _load_bbs_task_lifecycle()
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="netops",
        thread_id="th_task",
        eta="today",
        eta_at="2026-06-02T04:00:00Z",
        note="Picked up with a concrete ETA.",
        note_file=None,
    )

    assert module.cmd_ack(args) == 0
    assert calls == [
        (
            "POST",
            "http://bbs.local/api/v1/threads/th_task/ack",
            {
                "posted_by": "netops",
                "eta": "today",
                "eta_at": "2026-06-02T04:00:00Z",
                "note": "Picked up with a concrete ETA.",
            },
        )
    ]


def test_done_closes_thread_with_done_status(monkeypatch) -> None:
    module = _load_bbs_task_lifecycle()
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="netops",
        thread_id="th_task",
        reason="Resolver probe completed with evidence attached.",
        reason_file=None,
    )

    assert module.cmd_done(args) == 0
    assert calls == [
        (
            "POST",
            "http://bbs.local/api/v1/threads/th_task/status",
            {
                "status": "done",
                "posted_by": "netops",
                "reason": "Resolver probe completed with evidence attached.",
            },
        )
    ]


def test_done_can_append_ticket_cost_from_usage_db(tmp_path: Path, monkeypatch) -> None:
    module = _load_bbs_task_lifecycle()
    db_path = tmp_path / "tui_state.sqlite3"
    ledger_jsonl = tmp_path / "ticket_costs.jsonl"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE usage_events (
                thread_id TEXT,
                started_at INTEGER,
                runtime TEXT,
                model TEXT,
                service_tier TEXT,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens INTEGER,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO usage_events (
                thread_id, started_at, runtime, model, service_tier,
                input_tokens, cached_input_tokens, output_tokens,
                reasoning_output_tokens, total_tokens, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "codex-thread-a",
                10,
                "codex",
                "openai.gpt-5.5",
                "",
                1000,
                0,
                100,
                0,
                1100,
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="netops",
        thread_id="th_task",
        reason="Resolver probe completed with evidence attached.",
        reason_file=None,
        cost_ticket_id="CP-1",
        cost_ledger_jsonl=ledger_jsonl,
        cost_usage_db=db_path,
        cost_thread_id="codex-thread-a",
        cost_architecture_mode="hybrid",
        cost_price_basis="auto",
        cost_runtime="",
        cost_model="",
        cost_service_tier="",
        cost_input_tokens=0,
        cost_cached_input_tokens=0,
        cost_output_tokens=0,
        cost_reasoning_output_tokens=0,
        cost_total_tokens=0,
        cost_notes="closed from BBS lifecycle helper",
    )

    assert module.cmd_done(args) == 0
    assert calls == [
        (
            "POST",
            "http://bbs.local/api/v1/threads/th_task/status",
            {
                "status": "done",
                "posted_by": "netops",
                "reason": "Resolver probe completed with evidence attached.",
            },
        )
    ]
    records = [
        json.loads(line)
        for line in ledger_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["ticket"]["id"] == "CP-1"
    assert records[0]["source"]["kind"] == "usage_db"
    assert records[0]["source"]["thread_id"] == "codex-thread-a"
    assert records[0]["usage"]["usage_event_count"] == 1
    assert records[0]["usage"]["total_tokens"] == 1100
    assert records[0]["billing"]["price_basis"] == "bedrock-us-east-2"
    assert records[0]["cost"]["estimated_usd"] == 0.0088


def test_blocked_marks_thread_blocked_with_reason(monkeypatch) -> None:
    module = _load_bbs_task_lifecycle()
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="netops",
        thread_id="th_task",
        reason="Blocked waiting on owner token grant.",
        reason_file=None,
    )

    assert module.cmd_blocked(args) == 0
    assert calls == [
        (
            "POST",
            "http://bbs.local/api/v1/threads/th_task/status",
            {
                "status": "blocked",
                "posted_by": "netops",
                "reason": "Blocked waiting on owner token grant.",
            },
        )
    ]


def test_attach_files_uploads_then_posts_artifact_message(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_bbs_task_lifecycle()
    artifact_path = tmp_path / "matrix report.md"
    artifact_path.write_text("benchmark matrix\n", encoding="utf-8")
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, *, token="", payload=None, timeout=15.0):
        calls.append((method, url, payload or {}))
        if url.endswith("/api/v1/artifacts"):
            return {
                "ok": True,
                "artifact": {
                    "label": payload["label"],
                    "href": f"/artifacts/{payload['filename']}",
                    "bytes": len(base64.b64decode(payload["content_base64"])),
                    "sha256": payload["sha256"],
                },
            }
        return {"ok": True, "message": {"message_id": "msg_artifact"}}

    monkeypatch.setattr(module, "_request_json", fake_request)
    args = argparse.Namespace(
        url="http://bbs.local",
        token="token",
        actor="norman",
        thread_id="th_task",
        file=[str(artifact_path)],
        body="Attached benchmark artifacts.",
        body_file=None,
        name_prefix="run_1",
        overwrite=False,
        upload_timeout=99.0,
    )

    assert module.cmd_attach_files(args) == 0
    assert len(calls) == 2
    upload = calls[0]
    assert upload[0] == "POST"
    assert upload[1] == "http://bbs.local/api/v1/artifacts"
    assert upload[2]["uploaded_by"] == "norman"
    assert upload[2]["filename"] == "run_1_matrix_report.md"
    assert upload[2]["label"] == "matrix report.md"
    assert base64.b64decode(upload[2]["content_base64"]) == b"benchmark matrix\n"
    assert upload[2]["sha256"] == hashlib.sha256(b"benchmark matrix\n").hexdigest()

    message = calls[1]
    assert message == (
        "POST",
        "http://bbs.local/api/v1/threads/th_task/messages",
        {
            "posted_by": "norman",
            "kind": "artifact",
            "body": "Attached benchmark artifacts.",
            "artifacts": [
                {
                    "label": "matrix report.md",
                    "href": "/artifacts/run_1_matrix_report.md",
                }
            ],
        },
    )


def test_parser_defaults_to_configured_switchboard_env_file(monkeypatch) -> None:
    monkeypatch.setenv("SWITCHBOARD_ENV_FILE", "/etc/infra/switchboard-bbs.env")
    module = _load_bbs_task_lifecycle()

    args = module.build_parser().parse_args(["ack", "th_task", "--actor", "infra"])

    assert args.env_file == "/etc/infra/switchboard-bbs.env"
