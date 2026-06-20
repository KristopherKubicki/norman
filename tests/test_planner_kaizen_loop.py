from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "planner_kaizen_loop.py"
    spec = importlib.util.spec_from_file_location("planner_kaizen_loop", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_kaizen_loop"] = module
    spec.loader.exec_module(module)
    return module


def test_kaizen_loop_turns_watch_dimensions_into_measured_experiments() -> None:
    module = _load_module()

    report = module.build_report(
        {
            "schema": "norman.planner-excellence-scorecard.v1",
            "summary": {"gate": "pass", "maturity": "improving"},
            "dimensions": [
                {
                    "name": "timing_contract",
                    "status": "strong",
                    "score": 100,
                    "evidence": {"history_violation_count": 0},
                },
                {
                    "name": "offline_first",
                    "status": "watch",
                    "score": 15,
                    "evidence": {"spark_vllm_planner_candidate_count": 0},
                },
                {
                    "name": "route_stability",
                    "status": "watch",
                    "score": 20,
                    "evidence": {"route_drift_count": 4},
                },
            ],
        }
    )

    experiments = {
        experiment["dimension"]: experiment for experiment in report["experiments"]
    }
    assert report["schema"] == "norman.planner-kaizen-loop.v1"
    assert report["summary"]["experiment_count"] == 2
    assert report["summary"]["high_priority_experiment_count"] == 2
    assert report["summary"]["gate"] == "pass"
    assert experiments["offline_first"]["priority"] == "high"
    assert "Spark/vLLM" in experiments["offline_first"]["success_metric"]
    assert experiments["route_stability"]["pdca"]["check"].startswith(
        "route_drift_count"
    )
    assert report["model_calls_executed"] == 0


def test_kaizen_loop_fails_when_scorecard_has_failed_dimension() -> None:
    module = _load_module()

    report = module.build_report(
        {
            "dimensions": [
                {
                    "name": "safety",
                    "status": "fail",
                    "score": 40,
                    "evidence": {"block_count": 1},
                }
            ]
        }
    )

    assert report["summary"]["gate"] == "fail"
    assert report["summary"]["blocker_experiment_count"] == 1
    assert report["experiments"][0]["priority"] == "blocker"


def test_kaizen_loop_is_quiet_for_strong_scorecard() -> None:
    module = _load_module()

    report = module.build_report(
        {
            "dimensions": [
                {"name": "safety", "status": "strong", "score": 100},
                {"name": "timing_contract", "status": "strong", "score": 100},
            ]
        }
    )

    assert report["summary"]["experiment_count"] == 0
    assert report["summary"]["kaizen_active"] is False
    assert report["summary"]["gate"] == "pass"


def test_kaizen_loop_cli_writes_artifacts(tmp_path: Path) -> None:
    scorecard_json = tmp_path / "scorecard.json"
    output_json = tmp_path / "kaizen.json"
    output_md = tmp_path / "kaizen.md"
    scorecard_json.write_text(
        json.dumps(
            {"dimensions": [{"name": "spend_control", "status": "watch", "score": 80}]}
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_kaizen_loop.py",
            "--scorecard-json",
            str(scorecard_json),
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
    assert report["schema"] == "norman.planner-kaizen-loop.v1"
    assert report["summary"]["experiment_count"] == 1
    assert "Planner Kaizen Loop" in output_md.read_text(encoding="utf-8")
