from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_miner(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "work_session_runbook_miner",
        scripts_dir / "work_session_runbook_miner.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["work_session_runbook_miner"] = module
    spec.loader.exec_module(module)
    return module


def _write_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE turns (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            started_at INTEGER,
            model TEXT,
            service_tier TEXT,
            prompt_preview TEXT,
            response_preview TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    payloads = [
        {
            "id": "turn-netops",
            "thread_id": "thread-a",
            "started_at": 1781360000,
            "model": "gpt-5.5",
            "service_tier": "default",
            "prompt": "is netops wedged again? run tui_fleet_doctor and tui_fleet_scorecard",
            "response": "networking has ssh banner timeout and root disk pressure; restart is approval gated",
        },
        {
            "id": "turn-webgoat",
            "thread_id": "thread-b",
            "started_at": 1781360100,
            "model": "gpt-5.5",
            "service_tier": "default",
            "prompt": "webgoat merchant needs a proper xpath and jmespath parser fixture",
            "response": "build selector fixture, snapshot diff, and do not print cookie auth artifact token=abc123",
        },
        {
            "id": "turn-bbs",
            "thread_id": "thread-c",
            "started_at": 1781360200,
            "model": "gpt-5.5",
            "service_tier": "default",
            "prompt": "BBS handoff has unacked owner; should observer ACK or fork blocked done?",
            "response": "Do not ACK unless taking owner role; use bbs_task_lifecycle with reason.",
        },
    ]
    for payload in payloads:
        conn.execute(
            """
            INSERT INTO turns (
                id, thread_id, started_at, model, service_tier,
                prompt_preview, response_preview, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"],
                payload["thread_id"],
                payload["started_at"],
                payload["model"],
                payload["service_tier"],
                payload["prompt"][:120],
                payload["response"][:120],
                json.dumps(payload),
            ),
        )
    conn.commit()
    conn.close()


def _write_history(path: Path) -> None:
    rows = [
        {
            "thread_id": "thread-d",
            "started_at": 1781360300,
            "model": "gpt-5.5",
            "service_tier": "default",
            "prompt": "Gold Book SpecMaster attribute fill and validation builder for category creation",
            "response": "writespecs dry run, validator fixture, duplicate category check",
        },
        {
            "thread_id": "thread-e",
            "started_at": 1781360400,
            "model": "gpt-5.5",
            "service_tier": "default",
            "prompt": "work-special bedrock codex selected_runtime selected_model model picker for all 12",
            "response": "sync_agent_console_template verifies default_service_tier and Kimi/Claude lane",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_session(path: Path) -> None:
    rows = [
        {
            "timestamp": "2026-06-13T12:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": "session-control",
                "timestamp": "2026-06-13T12:00:00.000Z",
            },
        },
        {
            "timestamp": "2026-06-13T12:00:01.000Z",
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-control",
                "model": "gpt-5.4",
                "service_tier": "bedrock",
            },
        },
        {
            "timestamp": "2026-06-13T12:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "# AGENTS.md instructions for /repo\n\n<environment_context>ignore</environment_context>",
                    }
                ],
            },
        },
        {
            "timestamp": "2026-06-13T12:00:03.000Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "Find old sessions and build repeatable runbooks for work sessions, skills, tools, and the control plane always-on loop. Include common TUI working on status action, plan estimate, undo, unwind, remove queued prompt, and tenant boundary checks.",
            },
        },
        {
            "timestamp": "2026-06-13T12:00:04.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "functions.exec_command",
                "arguments": '{"cmd":"python scripts/work_loop_canary.py --shadow"}',
            },
        },
        {
            "timestamp": "2026-06-13T12:00:05.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": "control-plane safe action ladder queue depth receipt; no live writes in shadow; token=secret",
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _rows_by_id(report: dict) -> dict[str, dict]:
    return {str(row["pattern_id"]): row for row in report["rows"]}


def test_mines_sqlite_and_history_patterns(monkeypatch, tmp_path) -> None:
    module = _load_miner(monkeypatch)
    sqlite_path = tmp_path / "tui_state.sqlite3"
    history_path = tmp_path / "history.jsonl"
    _write_sqlite(sqlite_path)
    _write_history(history_path)

    turns = module.load_turns([sqlite_path], [history_path])
    report = module.build_report(turns, generated_at="2026-06-13T00:00:00Z")
    rows = _rows_by_id(report)

    assert report["schema"] == "norman.work-session-runbook-miner.v1"
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    assert report["turn_count"] == 5
    assert "tui_fleet_wedge_recovery" in rows
    assert "webgoat_selector_jmespath_merchant" in rows
    assert "goldbook_attribute_validator_category" in rows
    assert "work_special_model_lane_rollout" in rows
    assert "bbs_handoff_lifecycle" in rows
    assert (
        rows["webgoat_selector_jmespath_merchant"]["scores"]["hybrid_value_score"] > 0.6
    )
    assert (
        "Bedrock GPT-5.4"
        in rows["goldbook_attribute_validator_category"]["final_model_gate"]
    )


def test_mines_codex_session_logs(monkeypatch, tmp_path) -> None:
    module = _load_miner(monkeypatch)
    session_path = tmp_path / "rollout-session.jsonl"
    _write_session(session_path)

    turns = module.load_turns([], [], [session_path])
    report = module.build_report(turns, generated_at="2026-06-13T00:00:00Z")
    rows = _rows_by_id(report)

    assert report["turn_count"] == 1
    assert "control_plane_always_on_loop" in rows
    assert "tui_operator_common_workflows" in rows
    assert "session_runbook_promotion" in rows
    assert (
        rows["control_plane_always_on_loop"]["scores"]["comfort"]
        == "needs_more_cases_or_validator"
    )
    report_text = json.dumps(report)
    assert "token=secret" not in report_text
    assert "[REDACTED]" in report_text


def test_redacts_secret_like_values_in_evidence(monkeypatch, tmp_path) -> None:
    module = _load_miner(monkeypatch)
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "thread_id": "thread-secret",
                "started_at": 1781360500,
                "prompt": "webgoat xpath jmespath merchant auth artifact Authorization: Bearer supersecret +13126223100",
                "response": "cookie=hidden api_key=abc123 selector fixture",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.build_report(module.load_turns([], [history_path]))
    text = json.dumps(report)

    assert "supersecret" not in text
    assert "abc123" not in text
    assert "+13126223100" not in text
    assert "[PHONE_REDACTED]" in text
    assert "[REDACTED]" in text


def test_markdown_renders_candidate_matrix(monkeypatch, tmp_path) -> None:
    module = _load_miner(monkeypatch)
    sqlite_path = tmp_path / "tui_state.sqlite3"
    _write_sqlite(sqlite_path)

    markdown = module.render_markdown(
        module.build_report(module.load_turns([sqlite_path], []))
    )

    assert "# Work Session Runbook Miner" in markdown
    assert "## Candidate Matrix" in markdown
    assert "TUI fleet wedge detection" in markdown
    assert "WebGOAT selectors" in markdown
    assert "worker" in markdown.lower()


def test_cli_writes_json_and_markdown(monkeypatch, tmp_path, capsys) -> None:
    module = _load_miner(monkeypatch)
    history_path = tmp_path / "history.jsonl"
    session_path = tmp_path / "rollout-session.jsonl"
    output_json = tmp_path / "out.json"
    output_md = tmp_path / "out.md"
    output_candidates = tmp_path / "candidates"
    _write_history(history_path)
    _write_session(session_path)

    result = module.main(
        [
            "--history",
            str(history_path),
            "--session",
            str(session_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--output-candidates-dir",
            str(output_candidates),
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    summary = json.loads(captured.out)
    assert summary["candidate_count"] >= 2
    assert summary["candidate_files"] >= 3
    data = json.loads(output_json.read_text())
    assert data["turn_count"] == 3
    assert "Work Session Runbook Miner" in output_md.read_text()
    manifest = json.loads((output_candidates / "manifest.json").read_text())
    assert manifest["candidate_count"] >= 2
    candidate_text = (
        output_candidates / "goldbook-attribute-validator-category.md"
    ).read_text()
    assert "## Hybrid Model Split" in candidate_text
    assert "## Promotion Checklist" in candidate_text
