from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "planner_excellence_scorecard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "planner_excellence_scorecard", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_excellence_scorecard"] = module
    spec.loader.exec_module(module)
    return module


def test_excellence_scorecard_marks_clean_planner_as_spectacular_candidate() -> None:
    module = _load_module()

    report = module.build_report(
        guardrail={"summary": {"block_count": 0, "warn_count": 0}},
        preroute={
            "summary": {
                "skill_count": 10,
                "deterministic_bypass_count": 2,
                "local_planner_candidate_count": 8,
                "spark_vllm_planner_candidate_count": 8,
                "ollama_planner_candidate_count": 0,
                "cloud_candidate_requires_policy_check_count": 0,
            }
        },
        time_contract={
            "summary": {
                "gate": "pass",
                "policy_case_fail_count": 0,
                "history_violation_counts": {},
            }
        },
        route_policy={
            "summary": {
                "route_drift_count": 0,
                "spark_vllm_route_count": 8,
                "ollama_fallback_route_count": 0,
            }
        },
    )

    assert report["summary"]["gate"] == "pass"
    assert report["summary"]["maturity"] == "spectacular_candidate"
    assert report["summary"]["failed_dimensions"] == []
    assert report["summary"]["watch_dimensions"] == []
    assert report["summary"]["overall_score"] == 100
    assert report["model_calls_executed"] == 0


def test_excellence_scorecard_surfaces_watch_dimensions_without_failing_gate() -> None:
    module = _load_module()

    report = module.build_report(
        guardrail={"summary": {"block_count": 0, "warn_count": 2}},
        preroute={
            "summary": {
                "skill_count": 10,
                "deterministic_bypass_count": 1,
                "local_planner_candidate_count": 3,
                "spark_vllm_planner_candidate_count": 0,
                "ollama_planner_candidate_count": 3,
                "cloud_candidate_requires_policy_check_count": 6,
            }
        },
        time_contract={
            "summary": {
                "gate": "pass",
                "policy_case_fail_count": 0,
                "history_violation_counts": {"overrun_without_checkpoint": 1},
            }
        },
        route_policy={
            "summary": {
                "route_drift_count": 1,
                "spark_vllm_route_count": 0,
                "ollama_fallback_route_count": 3,
            }
        },
    )

    assert report["summary"]["gate"] == "pass"
    assert report["summary"]["maturity"] == "improving"
    assert report["summary"]["failed_dimensions"] == []
    assert set(report["summary"]["watch_dimensions"]) == {
        "safety",
        "timing_contract",
        "offline_first",
        "spend_control",
        "route_stability",
    }


def test_excellence_scorecard_fails_for_safety_or_timing_blocks() -> None:
    module = _load_module()

    report = module.build_report(
        guardrail={"summary": {"block_count": 1, "warn_count": 0}},
        preroute={
            "summary": {
                "skill_count": 5,
                "deterministic_bypass_count": 2,
                "local_planner_candidate_count": 3,
                "spark_vllm_planner_candidate_count": 3,
                "ollama_planner_candidate_count": 0,
                "cloud_candidate_requires_policy_check_count": 0,
            }
        },
        time_contract={
            "summary": {
                "gate": "fail",
                "policy_case_fail_count": 1,
                "history_violation_counts": {},
            }
        },
        route_policy={
            "summary": {
                "route_drift_count": 0,
                "spark_vllm_route_count": 3,
                "ollama_fallback_route_count": 0,
            }
        },
    )

    assert report["summary"]["gate"] == "fail"
    assert set(report["summary"]["failed_dimensions"]) == {"safety", "timing_contract"}


def test_excellence_scorecard_cli_writes_artifacts(tmp_path: Path) -> None:
    guardrail_json = tmp_path / "guardrail.json"
    preroute_json = tmp_path / "preroute.json"
    time_contract_json = tmp_path / "time.json"
    route_policy_json = tmp_path / "route.json"
    output_json = tmp_path / "scorecard.json"
    output_md = tmp_path / "scorecard.md"

    guardrail_json.write_text(
        json.dumps({"summary": {"block_count": 0, "warn_count": 0}}),
        encoding="utf-8",
    )
    preroute_json.write_text(
        json.dumps(
            {
                "summary": {
                    "skill_count": 1,
                    "deterministic_bypass_count": 1,
                    "local_planner_candidate_count": 0,
                    "spark_vllm_planner_candidate_count": 0,
                    "ollama_planner_candidate_count": 0,
                    "cloud_candidate_requires_policy_check_count": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    time_contract_json.write_text(
        json.dumps(
            {
                "summary": {
                    "gate": "pass",
                    "policy_case_fail_count": 0,
                    "history_violation_counts": {},
                }
            }
        ),
        encoding="utf-8",
    )
    route_policy_json.write_text(
        json.dumps(
            {
                "summary": {
                    "route_drift_count": 0,
                    "spark_vllm_route_count": 1,
                    "ollama_fallback_route_count": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_excellence_scorecard.py",
            "--guardrail-json",
            str(guardrail_json),
            "--preroute-json",
            str(preroute_json),
            "--time-contract-json",
            str(time_contract_json),
            "--route-policy-json",
            str(route_policy_json),
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
    assert report["schema"] == "norman.planner-excellence-scorecard.v1"
    assert report["summary"]["gate"] == "pass"
    assert "Planner Excellence Scorecard" in output_md.read_text(encoding="utf-8")
