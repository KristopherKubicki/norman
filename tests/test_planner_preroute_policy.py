from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "planner_preroute_policy.py"
    )
    spec = importlib.util.spec_from_file_location("planner_preroute_policy", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_preroute_policy"] = module
    spec.loader.exec_module(module)
    return module


def _row(
    skill_id: str,
    *,
    route_kind: str,
    runtime: str = "",
    provider: str = "",
    final_authority: bool = False,
) -> dict:
    return {
        "skill_id": skill_id,
        "domain": "gold-book",
        "family": "retrieval",
        "route_kind": route_kind,
        "network_priority": "offline_spark_vllm_preferred"
        if runtime == "spark_vllm"
        else "cloud_required",
        "selected_local_runtime_class": runtime,
        "selected_local_provider": provider,
        "selected_local_model": "Qwen/Qwen3-Coder-30B-A3B" if runtime else "",
        "spark_vllm_candidate_count": 1 if runtime == "spark_vllm" else 0,
        "ollama_candidate_count": 1 if runtime == "ollama" else 0,
        "offline_optimizer_state": "spark_vllm_selected"
        if runtime == "spark_vllm"
        else "",
        "final_authority_required": final_authority,
    }


def test_planner_preroute_prefers_deterministic_then_local_then_policy_cloud() -> None:
    module = _load_module()

    report = module.build_report(
        {
            "schema": "norman.local-model-route-policy.v1",
            "rows": [
                _row("count", route_kind="deterministic_only"),
                _row(
                    "code",
                    route_kind="local_then_5_4_verifier",
                    runtime="spark_vllm",
                    provider="vllm",
                ),
                _row(
                    "lookup",
                    route_kind="local_first",
                    runtime="ollama",
                    provider="ollama",
                ),
                _row("deploy", route_kind="cloud_only", final_authority=True),
            ],
        }
    )

    rows = {row["skill_id"]: row for row in report["rows"]}
    assert rows["count"]["pre_llm_decision"] == "bypass_llm_deterministic"
    assert rows["code"]["pre_llm_decision"] == "ask_spark_vllm_planner"
    assert rows["lookup"]["pre_llm_decision"] == "ask_ollama_planner"
    assert rows["deploy"]["pre_llm_decision"] == (
        "local_draft_cloud_final_policy_check"
    )
    assert rows["code"]["local_planner_contract"]["schema"] == (
        "norman.local-planner-proposal.v1"
    )
    assert rows["code"]["local_planner_contract_required"] is True
    assert rows["count"]["local_planner_contract_required"] is False
    assert report["summary"]["deterministic_bypass_count"] == 1
    assert report["summary"]["local_planner_candidate_count"] == 2
    assert report["summary"]["local_planner_contract_required_count"] == 2
    assert report["summary"]["cloud_candidate_requires_policy_check_count"] == 1
    assert report["model_calls_executed"] == 0


def test_planner_preroute_does_not_call_unavailable_local_runtime() -> None:
    module = _load_module()
    unavailable = _row(
        "lookup",
        route_kind="cloud_only",
        runtime="ollama",
        provider="ollama",
    )
    unavailable["local_runtime_routeable"] = False
    unavailable["local_runtime_health_status"] = "unavailable"
    unavailable["local_runtime_health_reason"] = "endpoint refused connection"

    report = module.build_report({"rows": [unavailable]})

    row = report["rows"][0]
    assert row["pre_llm_decision"] == "cloud_candidate_after_policy_check"
    assert row["decision_reason"] == "local runtime is unavailable"
    assert row["local_planner_candidate"] is False
    assert row["local_planner_contract_required"] is False
    assert report["summary"]["ollama_planner_candidate_count"] == 0
    assert report["summary"]["cloud_candidate_requires_policy_check_count"] == 1


def test_spark_prefilter_can_reduce_high_authority_work_without_finalizing() -> None:
    module = _load_module()
    row = _row(
        "release",
        route_kind="local_then_5_4_verifier",
        runtime="spark_vllm",
        provider="vllm",
        final_authority=True,
    )

    report = module.build_report({"rows": [row]})

    routed = report["rows"][0]
    assert routed["pre_llm_decision"] == "local_prefilter_cloud_final_policy_check"
    assert routed["local_planner_candidate"] is False
    assert routed["local_prefilter_candidate"] is True
    assert routed["cloud_verifier_required"] is True
    contract = routed["local_prefilter_contract"]
    assert contract["schema"] == "norman.local-prefilter-router-contract.v1"
    assert contract["advisory_only"] is True
    assert contract["policy_validator_required"] is True
    assert "final_authority" in contract["forbidden_outputs"]
    assert "authority_pressure" in contract["cloud_escalation_triggers"]
    assert report["summary"]["local_prefilter_candidate_count"] == 1
    assert report["summary"]["spark_prefilter_candidate_count"] == 1
    assert report["summary"]["cloud_verifier_required_count"] == 1


def test_local_planner_proposal_validator_enforces_policy_contract() -> None:
    module = _load_module()
    valid = {
        "schema": "norman.local-planner-proposal.v1",
        "route_class": "local_draft_cloud_verify",
        "confidence": 0.82,
        "required_evidence": ["tests/test_planner_preroute_policy.py"],
        "proposed_executor": "spark_vllm",
        "cloud_required": True,
        "max_cloud_spend_usd": 0.05,
        "stop_before_actions": ["cloud call", "live mutation"],
    }

    assert module.validate_local_planner_proposal(valid) == []

    invalid = {
        **valid,
        "route_class": "auto_execute_cloud_final",
        "cloud_required": True,
        "stop_before_actions": [],
    }
    errors = module.validate_local_planner_proposal(invalid)

    assert "route_class is not allowed" in errors
    assert "cloud_required proposals must stop before cloud/live action" in errors


def test_planner_preroute_cli_writes_artifacts(tmp_path: Path) -> None:
    route_policy = tmp_path / "route_policy.json"
    output_json = tmp_path / "planner_preroute.json"
    output_md = tmp_path / "planner_preroute.md"
    route_policy.write_text(
        json.dumps({"rows": [_row("count", route_kind="deterministic_only")]}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_preroute_policy.py",
            "--route-policy-json",
            str(route_policy),
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
    assert report["schema"] == "norman.planner-preroute-policy.v1"
    assert report["summary"]["deterministic_bypass_count"] == 1
    assert "Planner Pre-Route Policy" in output_md.read_text(encoding="utf-8")
