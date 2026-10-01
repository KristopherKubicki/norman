from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "agent_console_template"
    / "agent_console_session_budget.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "agent_console_session_budget_standalone",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_standalone_model_capability_uses_adjacent_registry(
    monkeypatch,
    tmp_path,
) -> None:
    registry = tmp_path / "model_roles.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "norman.norllama.model-roles.v1",
                "roles": {
                    "resident": {"model": "future-local", "capabilities": {}},
                    "economy": {"model": "future-luna", "capabilities": {}},
                    "authority": {
                        "model": "future-terra",
                        "aliases": ["future-authority"],
                        "capabilities": {"named_escalation_required": True},
                    },
                    "frontier": {"model": "future-sol", "capabilities": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_MODEL_ROLE_CONFIG", str(registry))
    module = _load_module()

    assert module.model_requires_named_escalation("future-terra") is True
    assert module.model_requires_named_escalation("future-authority") is True
    assert module.model_requires_named_escalation("unknown-model") is False


def test_standalone_model_capability_fails_conservatively_without_registry(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "NORMAN_MODEL_ROLE_CONFIG",
        str(tmp_path / "missing-model-roles.json"),
    )
    module = _load_module()

    assert module.model_requires_named_escalation("unknown-model") is False


def _usage_db(path: Path, rows: list[dict]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE usage_events (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            started_at INTEGER,
            finished_at INTEGER,
            input_tokens INTEGER,
            cached_input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            payload_json TEXT
        )
        """
    )
    for index, row in enumerate(rows):
        connection.execute(
            "INSERT INTO usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(index),
                "thread-a",
                100 + index,
                101 + index,
                0,
                0,
                0,
                int(row.get("total_tokens") or 0),
                json.dumps(row),
            ),
        )
    connection.commit()
    connection.close()


def _turns_db(path: Path, rows: list[dict]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE turns (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            started_at INTEGER,
            success INTEGER,
            payload_json TEXT
        )
        """
    )
    for index, row in enumerate(rows):
        connection.execute(
            "INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
            (
                str(index),
                "thread-a",
                100 + index,
                1 if row.get("success", True) else 0,
                json.dumps(row),
            ),
        )
    connection.commit()
    connection.close()


def _policy(module, **overrides):
    values = {
        "enabled": True,
        "checkpoint_tokens": 1_000_000,
        "reauthorization_tokens": 2_000_000,
        "max_age_seconds": 86_400,
        "max_tool_calls": 10_000,
        "require_named_escalation": False,
        "runaway_window_turns": 8,
        "max_recent_compactions": 2,
        "max_repeated_prompts": 3,
        "max_consecutive_failures": 3,
        "max_recent_tool_calls": 80,
        "max_recent_tokens": 100_000,
    }
    values.update(overrides)
    return module.SessionBudgetPolicy(**values)


def test_session_admission_stops_repeated_compaction_loop(tmp_path) -> None:
    module = _load_module()
    database = tmp_path / "state.db"
    _usage_db(
        database,
        [
            {
                "prompt": "/compact",
                "success": True,
                "session_admission_action": "checkpoint",
            },
            {
                "prompt": "compact this thread",
                "success": True,
                "session_admission_action": "checkpoint",
            },
        ],
    )

    decision = module.evaluate_admission(
        _policy(module),
        state_db_path=database,
        state_db_enabled=True,
        thread_id="thread-a",
        model="norman-code",
        reasoning_effort="medium",
    )

    assert decision["allowed"] is False
    assert decision["reason_code"] == "runaway_stop_required"
    assert decision["runaway_reasons"] == ["compaction_loop"]


def test_session_admission_checkpoints_dense_recent_usage(tmp_path) -> None:
    module = _load_module()
    database = tmp_path / "state.db"
    _usage_db(
        database,
        [
            {
                "prompt": f"task {index}",
                "success": True,
                "tool_call_count": 12,
                "total_tokens": 18_000,
            }
            for index in range(6)
        ],
    )

    decision = module.evaluate_admission(
        _policy(module),
        state_db_path=database,
        state_db_enabled=True,
        thread_id="thread-a",
        model="norman-code",
        reasoning_effort="medium",
    )

    assert decision["allowed"] is False
    assert decision["reason_code"] == "checkpoint_required"
    assert "run_health:token_window_pressure" in decision["checkpoint_reasons"]


def test_session_admission_stops_repeated_prompt_failure_loop(tmp_path) -> None:
    module = _load_module()
    database = tmp_path / "state.db"
    _usage_db(
        database,
        [
            {
                "prompt": "retry the same operation",
                "success": False,
                "total_tokens": 100,
            }
            for _ in range(3)
        ],
    )

    decision = module.evaluate_admission(
        _policy(module),
        state_db_path=database,
        state_db_enabled=True,
        thread_id="thread-a",
        model="norman-code",
        reasoning_effort="medium",
    )

    assert decision["allowed"] is False
    assert decision["reason_code"] == "runaway_stop_required"
    assert set(decision["runaway_reasons"]) == {
        "consecutive_failure_loop",
        "repeated_prompt_loop",
    }


def test_session_health_reads_prompt_evidence_from_turn_ledger(tmp_path) -> None:
    module = _load_module()
    database = tmp_path / "state.db"
    _usage_db(
        database,
        [{"success": False, "total_tokens": 100} for _ in range(3)],
    )
    _turns_db(
        database,
        [{"prompt": "retry the durable operation", "success": False} for _ in range(3)],
    )

    decision = module.evaluate_admission(
        _policy(module),
        state_db_path=database,
        state_db_enabled=True,
        thread_id="thread-a",
        model="norman-code",
        reasoning_effort="medium",
    )

    assert decision["allowed"] is False
    assert set(decision["runaway_reasons"]) == {
        "consecutive_failure_loop",
        "repeated_prompt_loop",
    }


def test_bounded_session_run_health_reads_recent_ledgers(tmp_path) -> None:
    module = _load_module()
    database = tmp_path / "state.db"
    _usage_db(
        database,
        [{"success": False, "total_tokens": 100} for _ in range(3)],
    )
    _turns_db(
        database,
        [{"prompt": "retry bounded work", "success": False} for _ in range(3)],
    )

    health = module.session_run_health(
        database,
        "thread-a",
        policy=_policy(module),
    )

    assert health["state"] == "stop"
    assert health["window_turns"] == 3
    assert {item["code"] for item in health["signals"]} == {
        "consecutive_failure_loop",
        "repeated_prompt_loop",
    }
