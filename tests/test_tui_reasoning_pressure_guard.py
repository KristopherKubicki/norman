from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_guard():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "tui_reasoning_pressure_guard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tui_reasoning_pressure_guard", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_reasoning_pressure_guard"] = module
    spec.loader.exec_module(module)
    return module


def _usage(
    *,
    model: str = "openai.gpt-5.4",
    speed: str = "medium",
    reasoning: int = 100,
    output: int = 300,
    prompt: str = "status?",
    response: str = "Ran tests; passed.",
    authority_pressure: bool = False,
) -> dict:
    return {
        "id": "turn-1",
        "prompt": prompt,
        "response": response,
        "authority_pressure": authority_pressure,
        "usage": {
            "model": model,
            "speed": speed,
            "input_tokens": 1000,
            "output_tokens": output,
            "reasoning_output_tokens": reasoning,
            "total_tokens": 1000 + output + reasoning,
        },
    }


def _route_policy() -> dict:
    return {
        "summary": {
            "network_priority_counts": {"local_preferred": 38},
            "estimated_cloud_savings_vs_bedrock_5_4_usd": 4.75,
            "estimated_5_5_authority_premium_vs_bedrock_5_4_usd": 0.25,
        }
    }


def _write_usage_db(path: Path, rows: list[dict]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE usage_events (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                runtime TEXT,
                model TEXT,
                speed TEXT,
                service_tier TEXT,
                success INTEGER,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens INTEGER,
                usage_meter_mode TEXT,
                payload_json TEXT
            )
            """
        )
        for row in rows:
            payload = row.get("payload_json")
            if isinstance(payload, dict):
                payload = json.dumps(payload)
            conn.execute(
                """
                INSERT INTO usage_events VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row.get("id", "usage-1"),
                    row.get("thread_id", "thread-1"),
                    row.get("started_at", 1),
                    row.get("finished_at", 2),
                    row.get("runtime", "codex"),
                    row.get("model", "openai.gpt-5.4"),
                    row.get("speed", "medium"),
                    row.get("service_tier", "standard"),
                    1,
                    row.get("input_tokens", 1000),
                    row.get("cached_input_tokens", 0),
                    row.get("output_tokens", 300),
                    row.get("reasoning_output_tokens", 100),
                    row.get("total_tokens", 1400),
                    row.get("usage_meter_mode", "per_turn"),
                    payload or "{}",
                ),
            )


def test_reasoning_pressure_guard_prefers_local_or_5_4_when_pressure_is_low() -> None:
    module = _load_guard()

    report = module.build_report([_usage()], route_policy=_route_policy())

    assert report["status"] == "ok"
    assert report["admission"]["action"] == "prefer_local_or_5_4"
    assert report["summary"]["local_preferred_routes"] == 38
    assert report["summary"]["estimated_savings_vs_5_4_usd"] == 4.75


def test_reasoning_pressure_guard_prompts_before_5_5_without_authority() -> None:
    module = _load_guard()

    report = module.build_report(
        [
            _usage(
                model="openai.gpt-5.5",
                speed="xhigh",
                reasoning=300,
                output=400,
                prompt="quick status?",
            )
        ],
        route_policy=_route_policy(),
    )

    assert report["status"] == "approval_recommended"
    assert report["admission"]["action"] == "ask_operator_before_5_5"
    assert {alert["kind"] for alert in report["alerts"]} >= {
        "frontier_without_authority_pressure",
        "high_effort_low_pressure_prompt",
    }


def test_reasoning_pressure_guard_allows_extra_reasoning_when_pressure_is_real() -> (
    None
):
    module = _load_guard()

    report = module.build_report(
        [
            _usage(
                model="openai.gpt-5.4",
                speed="high",
                reasoning=7000,
                output=1000,
                prompt="approval boundary for deploy?",
                authority_pressure=True,
            )
        ],
        route_policy=_route_policy(),
    )

    assert report["status"] == "pressure_confirmed"
    assert report["admission"]["action"] == "allow_extra_reasoning_with_checkpoint"
    assert report["alerts"][0]["kind"] == "reasoning_pressure_detected"


def test_reasoning_pressure_guard_catches_guessing_without_evidence() -> None:
    module = _load_guard()

    report = module.build_report(
        [
            _usage(
                reasoning=400,
                output=500,
                prompt="why is it down?",
                response="It is probably a network issue.",
            )
        ],
        route_policy=_route_policy(),
    )

    assert report["status"] == "warn"
    assert report["admission"]["action"] == "gather_evidence_before_spending_more"
    assert report["alerts"][0]["kind"] == "guessing_pressure"


def test_reasoning_pressure_guard_reads_latest_usage_events_from_sqlite(
    tmp_path: Path,
) -> None:
    module = _load_guard()
    db_path = tmp_path / "tui_state.sqlite3"
    _write_usage_db(
        db_path,
        [
            {
                "id": "old",
                "started_at": 100,
                "model": "openai.gpt-5.5",
                "speed": "xhigh",
                "payload_json": {"prompt": "quick status?"},
            },
            {
                "id": "new",
                "started_at": 200,
                "model": "openai.gpt-5.4",
                "speed": "medium",
                "payload_json": {"prompt": "status?", "response": "Ran jq; passed."},
            },
        ],
    )

    rows = module.load_usage_db_records(db_path, limit=1)
    report = module.build_report(rows, route_policy=_route_policy(), source="state_db")

    assert rows[0]["id"] == "new"
    assert report["status"] == "ok"
    assert report["summary"]["source"] == "state_db"


def test_reasoning_pressure_guard_cli_writes_json_and_markdown_from_db(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tui_state.sqlite3"
    policy_path = tmp_path / "policy.json"
    output_json = tmp_path / "guard.json"
    output_md = tmp_path / "guard.md"
    _write_usage_db(
        db_path,
        [
            {
                "id": "usage-5-5",
                "model": "openai.gpt-5.5",
                "speed": "xhigh",
                "payload_json": {"prompt": "quick status?"},
            }
        ],
    )
    policy_path.write_text(json.dumps(_route_policy()))

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/tui_reasoning_pressure_guard.py",
            "--usage-db",
            str(db_path),
            "--route-policy-json",
            str(policy_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["schema"] == "norman.tui.reasoning-pressure-guard.v1"
    assert report["dry_run_only"] is True
    assert report["summary"]["source"] == "state_db"
    assert report["admission"]["action"] == "ask_operator_before_5_5"
    assert "TUI Reasoning Pressure Guard" in output_md.read_text(encoding="utf-8")
