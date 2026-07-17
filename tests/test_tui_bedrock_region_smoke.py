from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_module():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "tui_bedrock_region_smoke",
        scripts_dir / "tui_bedrock_region_smoke.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_bedrock_region_smoke"] = module
    spec.loader.exec_module(module)
    return module


def _write_usage_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE usage_events (
                thread_id TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                runtime TEXT,
                model TEXT,
                service_tier TEXT,
                success INTEGER,
                output_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens INTEGER,
                provider_error_kind TEXT,
                provider_request_ids TEXT,
                provider_trace_ids TEXT,
                zero_token_provider_failure INTEGER,
                payload_json TEXT NOT NULL
            )
            """
        )
        for row in rows:
            conn.execute(
                """
                INSERT INTO usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("thread_id", ""),
                    row.get("started_at", 0),
                    row.get("finished_at", 0),
                    row.get("runtime", "codex"),
                    row.get("model", "openai.gpt-5.5"),
                    row.get("service_tier", "bedrock-failover"),
                    row.get("success", 0),
                    row.get("output_tokens", 0),
                    row.get("reasoning_output_tokens", 0),
                    row.get("total_tokens", 0),
                    row.get("provider_error_kind", ""),
                    json.dumps(row.get("provider_request_ids", [])),
                    json.dumps(row.get("provider_trace_ids", [])),
                    row.get("zero_token_provider_failure", 0),
                    json.dumps(row.get("payload_json", {})),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _bedrock_payload(**updates):
    payload = {
        "provider_surface": "aws-bedrock",
        "profile_v2": "traqline-bedrock-us-west-2",
        "aws_region": "us-west-2",
        "model": "openai.gpt-5.5",
    }
    payload.update(updates)
    return payload


def test_region_smoke_marks_exact_success_ok(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "tui_state.sqlite3"
    _write_usage_db(
        db_path,
        [
            {
                "thread_id": "ok-thread",
                "started_at": 100,
                "finished_at": 120,
                "success": 1,
                "total_tokens": 42,
                "payload_json": _bedrock_payload(success=True, total_tokens=42),
            }
        ],
    )

    records = module.load_usage_records([("panelbot", db_path)], since_ts=0)
    report = module.build_smoke_report(
        records,
        profile_v2="traqline-bedrock-us-west-2",
        model="openai.gpt-5.5",
        aws_region="us-west-2",
        since_ts=0,
        checked_at=200,
    )

    profile = report["profiles"]["traqline-bedrock-us-west-2"]
    assert profile["ok"] is True
    assert profile["status"] == "ok"
    assert profile["successes"] == 1
    assert profile["failures"] == 0


def test_region_smoke_preserves_failed_request_ids(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "tui_state.sqlite3"
    _write_usage_db(
        db_path,
        [
            {
                "thread_id": "fail-thread",
                "started_at": 100,
                "finished_at": 120,
                "success": 0,
                "total_tokens": 0,
                "provider_error_kind": "bedrock_engine_not_found",
                "provider_request_ids": ["aws-request-123"],
                "zero_token_provider_failure": 1,
                "payload_json": _bedrock_payload(
                    success=False,
                    total_tokens=0,
                    provider_error_kind="bedrock_engine_not_found",
                ),
            }
        ],
    )

    records = module.load_usage_records([("panelbot", db_path)], since_ts=0)
    report = module.build_smoke_report(
        records,
        profile_v2="traqline-bedrock-us-west-2",
        model="openai.gpt-5.5",
        aws_region="us-west-2",
        since_ts=0,
        checked_at=200,
    )

    profile = report["profiles"]["traqline-bedrock-us-west-2"]
    assert profile["ok"] is False
    assert profile["status"] == "failing"
    assert profile["failures"] == 1
    assert profile["zero_token_failures"] == 1
    assert profile["failure_kinds"] == {"bedrock_engine_not_found": 1}
    assert profile["provider_request_ids"] == ["aws-request-123"]


def test_region_smoke_does_not_match_wrong_region(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "tui_state.sqlite3"
    _write_usage_db(
        db_path,
        [
            {
                "thread_id": "ok-thread",
                "started_at": 100,
                "finished_at": 120,
                "success": 1,
                "total_tokens": 42,
                "payload_json": _bedrock_payload(
                    success=True,
                    total_tokens=42,
                    aws_region="us-east-2",
                    profile_v2="traqline-bedrock",
                ),
            }
        ],
    )

    records = module.load_usage_records([("panelbot", db_path)], since_ts=0)
    report = module.build_smoke_report(
        records,
        profile_v2="traqline-bedrock-us-west-2",
        model="openai.gpt-5.5",
        aws_region="us-west-2",
        since_ts=0,
        checked_at=200,
    )

    profile = report["profiles"]["traqline-bedrock-us-west-2"]
    assert profile["ok"] is False
    assert profile["status"] == "unknown"
    assert profile["successes"] == 0
    assert profile["failures"] == 0


def test_live_smoke_report_runs_codex_candidate(monkeypatch) -> None:
    module = _load_module()
    calls = []

    def fake_run(cmd, text, stdout, stderr, timeout, check, env=None):
        if cmd == ["/usr/local/bin/codex", "exec", "--help"]:
            return module.subprocess.CompletedProcess(
                cmd, 0, stdout="--profile", stderr=""
            )
        calls.append((cmd, env, timeout))
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text("BEDROCK_SMOKE_OK_profile_us_east_1", encoding="utf-8")
        return module.subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"type":"thread.started","thread_id":"t1"}\n{"type":"turn.completed"}\n',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    report = module.build_live_smoke_report(
        candidates=[("profile", "us-east-1")],
        model="openai.gpt-5.5",
        codex_bin="/usr/local/bin/codex",
        codex_home="/tmp/codex-home",
        workdir="/tmp",
        timeout_seconds=90,
    )

    profile = report["profiles"]["profile"]
    assert report["source"] == "live-codex"
    assert profile["ok"] is True
    assert profile["status"] == "ok"
    assert profile["event_types"] == ["thread.started", "turn.completed"]
    cmd, env, timeout = calls[0]
    assert cmd[cmd.index("--profile") + 1] == "profile"
    assert cmd[cmd.index("-m") + 1] == "openai.gpt-5.5"
    assert 'model_reasoning_effort="low"' in cmd
    assert env["CODEX_HOME"] == "/tmp/codex-home"
    assert env["AWS_REGION"] == "us-east-1"
    assert timeout == 90


def test_live_smoke_uses_legacy_profile_flag_when_required(monkeypatch) -> None:
    module = _load_module()
    calls = []

    def fake_run(cmd, text, stdout, stderr, timeout, check, env=None):
        if cmd == ["codex", "exec", "--help"]:
            return module.subprocess.CompletedProcess(
                cmd, 0, stdout="--profile-v2", stderr=""
            )
        calls.append((cmd, env, timeout))
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text("BEDROCK_SMOKE_OK_profile_us_east_1", encoding="utf-8")
        return module.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    report = module.build_live_smoke_report(
        candidates=[("profile", "us-east-1")],
        model="openai.gpt-5.5",
        codex_bin="codex",
        codex_home="",
        workdir="/tmp",
        timeout_seconds=90,
    )

    assert report["profiles"]["profile"]["ok"] is True
    assert calls[0][0][calls[0][0].index("--profile-v2") + 1] == "profile"


def test_live_smoke_report_classifies_stream_disconnect(monkeypatch) -> None:
    module = _load_module()

    def fake_run(cmd, text, stdout, stderr, timeout, check, env=None):
        if cmd == ["codex", "exec", "--help"]:
            return module.subprocess.CompletedProcess(
                cmd, 0, stdout="--profile", stderr=""
            )
        return module.subprocess.CompletedProcess(
            cmd,
            1,
            stdout=(
                '{"type":"error","message":"stream disconnected before completion: '
                'The server had an error while processing your request."}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    report = module.build_live_smoke_report(
        candidates=[("profile", "us-east-1")],
        model="openai.gpt-5.5",
        codex_bin="codex",
        codex_home="",
        workdir="/tmp",
        timeout_seconds=90,
    )

    profile = report["profiles"]["profile"]
    assert profile["ok"] is False
    assert profile["status"] == "failing"
    assert profile["provider_error_kind"] == "bedrock_stream_disconnected"
