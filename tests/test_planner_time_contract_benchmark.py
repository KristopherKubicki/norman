from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "planner_time_contract_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location(
        "planner_time_contract_benchmark", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_time_contract_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def test_time_contract_benchmark_scores_default_policy_cases() -> None:
    module = _load_module()

    report = module.build_report()

    assert report["schema"] == "norman.planner-time-contract-benchmark.v1"
    assert report["summary"]["gate"] == "pass"
    assert report["summary"]["case_count"] == 5
    assert report["summary"]["policy_case_count"] == 5
    assert report["summary"]["history_observation_count"] == 0
    assert report["summary"]["policy_case_fail_count"] == 0
    assert report["summary"]["detected_violation_counts"] == {
        "overrun_without_checkpoint": 1,
        "premature_return_without_evidence": 1,
        "proceed_did_not_use_checkpoint": 1,
    }
    assert report["model_calls_executed"] == 0


def test_time_contract_benchmark_fails_policy_mismatch() -> None:
    module = _load_module()

    report = module.build_report(
        [
            {
                "case_id": "bad-empty-plan",
                "prompt": "work on this for hours",
                "work_class": "long_work",
                "requested_target_seconds": 7200,
                "elapsed_seconds": 2,
                "time_contract_present": True,
                "evidence_count": 0,
                "final_status": "done",
                "expected_violation_codes": [],
            }
        ]
    )

    assert report["summary"]["gate"] == "fail"
    assert report["summary"]["policy_case_fail_count"] == 1
    assert report["rows"][0]["detected_violation_codes"] == [
        "premature_return_without_evidence"
    ]


def test_time_contract_benchmark_loads_history_observations(tmp_path: Path) -> None:
    module = _load_module()
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute(
        """
        CREATE TABLE turns (
            id TEXT PRIMARY KEY,
            started_at INTEGER,
            finished_at INTEGER,
            job_budget TEXT,
            timeout_seconds INTEGER,
            prompt_preview TEXT,
            response_preview TEXT,
            prompt_chars INTEGER,
            response_chars INTEGER,
            usage_total_tokens INTEGER,
            success INTEGER,
            payload_json TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO turns VALUES (
            'slow-no-checkpoint', 100, 5000, '5m', 300,
            'this should be a five minute check',
            'still working but no progress marker',
            42, 1000, 100, 1, '{}'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO turns VALUES (
            'normal-status', 100, 104, '5m', 300,
            'status?',
            'done',
            7, 20, 10, 1, '{}'
        )
        """
    )
    conn.commit()
    conn.close()

    history_cases = module.load_history_cases(state_db, limit=10)
    report = module.build_report(list(module.DEFAULT_CASES) + history_cases)

    assert len(history_cases) == 2
    assert report["summary"]["gate"] == "pass"
    assert report["summary"]["history_observation_count"] == 2
    assert report["summary"]["history_violation_counts"] == {
        "overrun_without_checkpoint": 1
    }


def test_time_contract_benchmark_cli_writes_artifacts(tmp_path: Path) -> None:
    output_json = tmp_path / "time_contract.json"
    output_md = tmp_path / "time_contract.md"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_time_contract_benchmark.py",
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
    assert report["schema"] == "norman.planner-time-contract-benchmark.v1"
    assert report["summary"]["gate"] == "pass"
    assert "Planner Time Contract Benchmark" in output_md.read_text(encoding="utf-8")
