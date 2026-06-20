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
        / "planner_guardrail_dashboard.py"
    )
    spec = importlib.util.spec_from_file_location("planner_guardrail_dashboard", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_guardrail_dashboard"] = module
    spec.loader.exec_module(module)
    return module


def test_guardrail_dashboard_promotes_blocks_warnings_and_observations() -> None:
    module = _load_module()

    report = module.build_report(
        cutover={
            "schema": "norman.tui-cutover-readiness.v1",
            "summary": {
                "boundary_violation_count": 1,
                "live_write_attempt_count": 0,
                "route_receipt_chain_issue_count": 0,
                "route_drift_count": 4,
                "blocked_target_count": 3,
            },
        },
        preroute={
            "schema": "norman.planner-preroute-policy.v1",
            "summary": {
                "cloud_candidate_requires_policy_check_count": 292,
                "local_planner_contract_required_count": 72,
            },
        },
        route_policy={
            "schema": "norman.local-model-route-policy.v1",
            "summary": {
                "ollama_fallback_route_count": 72,
                "spark_vllm_route_count": 0,
            },
        },
        local_floors={
            "schema": "norman.local-model-skill-floor.v1",
            "summary": {"online_spark_vllm_model_count": 0},
        },
    )

    signal_codes = {signal["code"] for signal in report["signals"]}
    assert report["summary"] == {
        "signal_count": 7,
        "block_count": 1,
        "warn_count": 5,
        "observe_count": 1,
        "needs_attention": True,
    }
    assert signal_codes == {
        "boundary_violation",
        "route_drift",
        "blocked_cutover_targets",
        "cloud_policy_check_queue",
        "spark_vllm_unavailable",
        "ollama_fallback_without_spark",
        "local_planner_contracts_required",
    }
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0


def test_guardrail_dashboard_stays_quiet_when_inputs_are_clean() -> None:
    module = _load_module()

    report = module.build_report(
        cutover={
            "summary": {
                "boundary_violation_count": 0,
                "live_write_attempt_count": 0,
                "route_receipt_chain_issue_count": 0,
                "route_drift_count": 0,
                "blocked_target_count": 0,
            }
        },
        preroute={
            "summary": {
                "cloud_candidate_requires_policy_check_count": 0,
                "local_planner_contract_required_count": 0,
            }
        },
        route_policy={
            "summary": {
                "ollama_fallback_route_count": 0,
                "spark_vllm_route_count": 12,
            }
        },
        local_floors={"summary": {"online_spark_vllm_model_count": 1}},
    )

    assert report["summary"] == {
        "signal_count": 0,
        "block_count": 0,
        "warn_count": 0,
        "observe_count": 0,
        "needs_attention": False,
    }
    assert report["signals"] == []


def test_guardrail_dashboard_cli_writes_artifacts(tmp_path: Path) -> None:
    cutover_json = tmp_path / "cutover.json"
    preroute_json = tmp_path / "preroute.json"
    route_policy_json = tmp_path / "route_policy.json"
    local_floors_json = tmp_path / "local_floors.json"
    output_json = tmp_path / "dashboard.json"
    output_md = tmp_path / "dashboard.md"
    cutover_json.write_text(
        json.dumps({"summary": {"route_drift_count": 1}}),
        encoding="utf-8",
    )
    preroute_json.write_text(
        json.dumps({"summary": {"local_planner_contract_required_count": 2}}),
        encoding="utf-8",
    )
    route_policy_json.write_text(
        json.dumps({"summary": {"spark_vllm_route_count": 1}}),
        encoding="utf-8",
    )
    local_floors_json.write_text(
        json.dumps({"summary": {"online_spark_vllm_model_count": 1}}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_guardrail_dashboard.py",
            "--cutover-json",
            str(cutover_json),
            "--preroute-json",
            str(preroute_json),
            "--route-policy-json",
            str(route_policy_json),
            "--local-floors-json",
            str(local_floors_json),
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
    assert report["schema"] == "norman.planner-guardrail-dashboard.v1"
    assert report["summary"]["warn_count"] == 1
    assert report["summary"]["observe_count"] == 1
    assert "Planner Guardrail Dashboard" in output_md.read_text(encoding="utf-8")
