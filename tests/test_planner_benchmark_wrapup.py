from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "planner_benchmark_wrapup.py"
    )
    spec = importlib.util.spec_from_file_location("planner_benchmark_wrapup", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_benchmark_wrapup"] = module
    spec.loader.exec_module(module)
    return module


def _scorecard(watches: int = 0) -> dict:
    return {
        "schema": "norman.planner-excellence-scorecard.v1",
        "summary": {
            "overall_score": 100 if watches == 0 else 63,
            "gate": "pass",
            "maturity": "spectacular_candidate" if watches == 0 else "improving",
            "watch_dimension_count": watches,
        },
    }


def _skill_matrix() -> dict:
    return {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "summary": {
            "recommended_bedrock_pipeline_total_usd": 109.136715,
            "openai_frontier_fast_xhigh_total_usd": 386.372625,
            "spark_guarded_pipeline_total_usd": 107.963346,
            "spark_savings_vs_current_recommended_usd": 1.173369,
        },
    }


def test_wrapup_blocks_more_offline_when_runtime_and_promotion_are_missing() -> None:
    module = _load_module()

    report = module.build_report(
        scorecard=_scorecard(watches=4),
        route_policy={
            "schema": "norman.local-model-route-policy.v1",
            "summary": {
                "skill_count": 366,
                "cloud_candidate_requires_policy_check_count": 364,
                "offline_first_route_count": 2,
                "spark_vllm_route_count": 0,
                "ollama_fallback_route_count": 0,
                "estimated_cloud_savings_usd": 0.06413,
            },
        },
        runtime_health={
            "schema": "norman.local-runtime-health.v1",
            "summary": {"healthy_runtime_count": 0},
        },
        skill_matrix=_skill_matrix(),
        llm_score={
            "schema": "norman.planner-llm-benchmark-score.v1",
            "summary": {"gate": "fail", "local_promoted_role_count": 0},
        },
    )

    summary = report["summary"]
    assert summary["planner_state"] == "improving"
    assert summary["optimizer_state"] == "guarded_cloud_policy_ready"
    assert summary["more_live_offline_ready"] is False
    assert summary["personal_offline_ready"] is False
    assert "no_healthy_local_runtime" in summary["offline_blockers"]
    assert "no_passing_local_promotion_record" in summary["offline_blockers"]
    assert summary["modeled_bedrock_vs_openai_frontier_savings_usd"] == 277.23591


def test_wrapup_marks_personal_and_work_offline_ready_when_gates_are_clean() -> None:
    module = _load_module()

    report = module.build_report(
        scorecard=_scorecard(watches=0),
        route_policy={
            "schema": "norman.local-model-route-policy.v1",
            "summary": {
                "skill_count": 366,
                "cloud_candidate_requires_policy_check_count": 180,
                "offline_first_route_count": 186,
                "spark_vllm_route_count": 120,
                "ollama_fallback_route_count": 20,
                "estimated_cloud_savings_usd": 42.0,
            },
        },
        runtime_health={
            "schema": "norman.local-runtime-health.v1",
            "summary": {"healthy_runtime_count": 2},
        },
        skill_matrix=_skill_matrix(),
        llm_score={
            "schema": "norman.planner-llm-benchmark-score.v1",
            "summary": {"gate": "pass", "local_promoted_role_count": 4},
        },
    )

    summary = report["summary"]
    assert summary["planner_state"] == "strong"
    assert summary["more_live_offline_ready"] is True
    assert summary["personal_offline_ready"] is True
    assert summary["work_offline_ready"] is True
    assert summary["offline_blockers"] == []


def test_wrapup_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    module = _load_module()
    inputs = {
        "scorecard": _scorecard(watches=4),
        "route": {
            "schema": "norman.local-model-route-policy.v1",
            "summary": {
                "skill_count": 1,
                "cloud_candidate_requires_policy_check_count": 1,
            },
        },
        "preroute": {
            "schema": "norman.planner-preroute-policy.v1",
            "summary": {
                "skill_count": 1,
                "cloud_candidate_requires_policy_check_count": 1,
            },
        },
        "runtime": {
            "schema": "norman.local-runtime-health.v1",
            "summary": {"healthy_runtime_count": 0},
        },
        "skill": _skill_matrix(),
        "llm": {
            "schema": "norman.planner-llm-benchmark-score.v1",
            "summary": {"gate": "fail", "local_promoted_role_count": 0},
        },
    }
    paths = {}
    for name, payload in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    output_json = tmp_path / "wrapup.json"
    output_md = tmp_path / "wrapup.md"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_benchmark_wrapup.py",
            "--scorecard-json",
            str(paths["scorecard"]),
            "--route-policy-json",
            str(paths["route"]),
            "--preroute-json",
            str(paths["preroute"]),
            "--runtime-health-json",
            str(paths["runtime"]),
            "--skill-matrix-json",
            str(paths["skill"]),
            "--llm-score-json",
            str(paths["llm"]),
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
    assert report["schema"] == module.SCHEMA
    assert "Planner Benchmark Wrap-Up" in output_md.read_text(encoding="utf-8")
