from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "local_model_route_policy.py"
    )
    spec = importlib.util.spec_from_file_location("local_model_route_policy", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_model_route_policy"] = module
    spec.loader.exec_module(module)
    return module


def _floor(
    skill_id: str,
    *,
    status: str,
    role: str,
    final: bool = False,
    provider: str = "ollama",
    runtime_class: str = "ollama",
    offline_state: str = "ollama_fallback_no_usable_spark_vllm",
) -> dict:
    return {
        "skill_id": skill_id,
        "domain": "gold-book",
        "family": "retrieval",
        "label": skill_id,
        "local_floor_status": status,
        "allowed_role": role,
        "selected_local_model": "gpt-oss:20b",
        "selected_local_endpoint": "http://192.168.2.150:11434",
        "selected_local_model_family": "small_local_worker",
        "selected_local_provider": provider,
        "selected_local_runtime_class": runtime_class,
        "selected_local_source_schema": f"norman.tui.{provider}-sense.v1",
        "selected_local_endpoint_scope": "lan",
        "spark_vllm_candidate_count": 1 if runtime_class == "spark_vllm" else 0,
        "ollama_candidate_count": 1 if provider == "ollama" else 0,
        "offline_optimizer_state": offline_state,
        "validator_gate": "fixture validator",
        "final_authority_required": final,
        "escalate_to_5_4_when": ["validator fails"],
        "escalate_to_5_5_when": ["authority boundary"],
    }


def _matrix(skill_id: str, *, baseline: float = 1.0, verifier: float = 0.5) -> dict:
    return {
        "skill_id": skill_id,
        "all_bedrock_5_5_xhigh_cost_usd": baseline,
        "bedrock_5_4_xhigh_cost_usd": verifier,
        "recommended_pipeline_cost_usd": verifier,
    }


def test_route_policy_prioritizes_local_and_counts_conservative_savings() -> None:
    module = _load_module()
    report = module.build_report(
        {
            "schema": "norman.local-model-skill-floor.v1",
            "rows": [
                _floor(
                    "lookup",
                    status="local_validator_bounded_final_candidate",
                    role="validator_bounded_final_candidate",
                ),
                _floor(
                    "draft",
                    status="local_worker_with_bedrock_5_4_verifier",
                    role="worker_draft",
                ),
                _floor(
                    "deploy",
                    status="local_draft_only_final_authority_hold",
                    role="draft_only",
                    final=True,
                ),
            ],
        },
        {
            "schema": "norman.work-domain-skill-benchmark.v1",
            "rows": [
                _matrix("lookup", baseline=1.0, verifier=0.5),
                _matrix("draft", baseline=2.0, verifier=0.75),
                _matrix("deploy", baseline=4.0, verifier=1.5),
            ],
        },
    )

    rows = {row["skill_id"]: row for row in report["rows"]}
    assert rows["lookup"]["route_kind"] == "local_first"
    assert rows["lookup"]["network_priority"] == "offline_ollama_fallback"
    assert rows["lookup"]["offline_first_route"] is True
    assert rows["lookup"]["estimated_cloud_savings_usd"] == 1.0
    assert rows["lookup"]["estimated_cloud_savings_vs_bedrock_5_4_usd"] == 0.5
    assert rows["draft"]["route_kind"] == "local_then_5_4_verifier"
    assert rows["draft"]["estimated_cloud_savings_usd"] == 1.25
    assert rows["draft"]["estimated_cloud_savings_vs_bedrock_5_4_usd"] == 0.0
    assert rows["deploy"]["route_kind"] == "local_draft_final_hold"
    assert rows["deploy"]["estimated_cloud_savings_usd"] == 0.0
    assert rows["deploy"]["estimated_5_5_authority_premium_vs_bedrock_5_4_usd"] == 2.5
    assert report["summary"]["baseline_all_bedrock_5_5_xhigh_cost_usd"] == 7.0
    assert report["summary"]["baseline_all_bedrock_5_4_xhigh_cost_usd"] == 2.75
    assert report["summary"]["baseline_recommended_pipeline_cost_usd"] == 2.75
    assert report["summary"]["estimated_policy_cloud_cost_usd"] == 4.75
    assert report["summary"]["estimated_policy_cloud_cost_vs_bedrock_5_4_usd"] == 4.75
    assert report["summary"]["estimated_cloud_savings_usd"] == 2.25
    assert report["summary"]["estimated_cloud_savings_pct"] == 32.14
    assert report["summary"]["estimated_cloud_savings_vs_bedrock_5_4_usd"] == 0.5
    assert report["summary"]["estimated_cloud_savings_vs_bedrock_5_4_pct"] == 18.18
    assert report["summary"]["estimated_cloud_savings_vs_recommended_usd"] == 0.5
    assert (
        report["summary"]["estimated_5_5_authority_premium_vs_bedrock_5_4_usd"] == 2.5
    )
    assert report["summary"]["offline_first_route_count"] == 2
    assert report["summary"]["ollama_fallback_route_count"] == 2


def test_route_policy_marks_spark_vllm_offline_priority() -> None:
    module = _load_module()
    report = module.build_report(
        {
            "rows": [
                _floor(
                    "code_patch",
                    status="local_worker_with_bedrock_5_4_verifier",
                    role="worker_draft",
                    provider="vllm",
                    runtime_class="spark_vllm",
                    offline_state="spark_vllm_selected",
                )
            ]
        },
        {"rows": [_matrix("code_patch", baseline=2.0, verifier=0.75)]},
    )

    row = report["rows"][0]
    assert row["network_priority"] == "offline_spark_vllm_preferred"
    assert row["selected_local_provider"] == "vllm"
    assert row["selected_local_runtime_class"] == "spark_vllm"
    assert row["offline_optimizer_state"] == "spark_vllm_selected"
    assert report["summary"]["spark_vllm_route_count"] == 1
    assert report["summary"]["selected_runtime_counts"]["spark_vllm"] == 1


def test_route_policy_demotes_unhealthy_local_runtime_to_cloud_required() -> None:
    module = _load_module()
    report = module.build_report(
        {
            "rows": [
                _floor(
                    "lookup",
                    status="local_validator_bounded_final_candidate",
                    role="validator_bounded_final_candidate",
                )
            ]
        },
        {"rows": [_matrix("lookup", baseline=2.0, verifier=0.75)]},
        runtime_health={
            "schema": "norman.local-runtime-health.v1",
            "runtimes": [
                {
                    "runtime_class": "ollama",
                    "provider": "ollama",
                    "status": "unavailable",
                    "routeable": False,
                    "reason": "endpoint refused connection",
                }
            ],
        },
    )

    row = report["rows"][0]
    assert row["route_kind"] == "cloud_only"
    assert row["network_priority"] == "local_runtime_unavailable_cloud_required"
    assert row["offline_first_route"] is False
    assert row["local_runtime_routeable"] is False
    assert row["local_runtime_health_status"] == "unavailable"
    assert row["estimated_cloud_savings_usd"] == 0.0
    assert report["summary"]["local_runtime_unavailable_count"] == 1
    assert report["summary"]["offline_first_route_count"] == 0
    assert report["summary"]["ollama_fallback_route_count"] == 0


def test_route_policy_keeps_healthy_runtime_routeable() -> None:
    module = _load_module()
    report = module.build_report(
        {
            "rows": [
                _floor(
                    "lookup",
                    status="local_validator_bounded_final_candidate",
                    role="validator_bounded_final_candidate",
                )
            ]
        },
        {"rows": [_matrix("lookup", baseline=2.0, verifier=0.75)]},
        runtime_health={
            "schema": "norman.local-runtime-health.v1",
            "runtimes": [
                {
                    "runtime_class": "ollama",
                    "provider": "ollama",
                    "status": "healthy",
                    "routeable": True,
                    "model_count": 3,
                }
            ],
        },
    )

    row = report["rows"][0]
    assert row["route_kind"] == "local_first"
    assert row["network_priority"] == "offline_ollama_fallback"
    assert row["offline_first_route"] is True
    assert row["local_runtime_routeable"] is True
    assert row["local_runtime_health_status"] == "healthy"
    assert report["summary"]["local_runtime_unavailable_count"] == 0
    assert report["summary"]["offline_first_route_count"] == 1


def test_route_policy_defers_cloud_heavy_when_pressure_guard_says_defer() -> None:
    module = _load_module()
    report = module.build_report(
        {
            "rows": [
                _floor(
                    "deploy",
                    status="local_draft_only_final_authority_hold",
                    role="draft_only",
                    final=True,
                )
            ]
        },
        {"rows": [_matrix("deploy", baseline=4.0, verifier=1.5)]},
        pressure_guard={
            "status": "watching",
            "admission": {
                "action": "defer_heavy_work",
                "reason": "swap_used_ratio>=0.25",
            },
        },
    )

    assert report["pressure_admission"]["action"] == "defer_heavy_work"
    assert report["rows"][0]["network_priority"] == "defer_cloud_heavy"


def test_route_policy_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    floors = tmp_path / "floors.json"
    matrix = tmp_path / "matrix.json"
    pressure = tmp_path / "pressure.json"
    output_json = tmp_path / "policy.json"
    output_md = tmp_path / "policy.md"
    floors.write_text(
        json.dumps(
            {
                "rows": [
                    _floor(
                        "lookup",
                        status="local_validator_bounded_final_candidate",
                        role="validator_bounded_final_candidate",
                    )
                ]
            }
        ),
        encoding="utf-8",
    )
    matrix.write_text(json.dumps({"rows": [_matrix("lookup")]}), encoding="utf-8")
    pressure.write_text(
        json.dumps({"status": "healthy", "admission": {"action": "accept_new_work"}}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/local_model_route_policy.py",
            "--skill-floors-json",
            str(floors),
            "--skill-matrix-json",
            str(matrix),
            "--pressure-guard-json",
            str(pressure),
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
    assert report["schema"] == "norman.local-model-route-policy.v1"
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    markdown = output_md.read_text(encoding="utf-8")
    assert "Local-First Route Policy" in markdown
    assert "Why This Saves Money" in markdown
    assert "Estimated cloud savings vs all-5.4" in markdown
