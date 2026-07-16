import app.services.norllama.specialist_lanes as specialist_lanes
from app.services.norllama.specialist_lanes import (
    ALLOWED_SPECIALIST_STATES,
    SPECIALIST_CASCADE_SCHEMA,
    SPECIALIST_LANE_REGISTRY_SCHEMA,
    SPECIALIST_PROOF_SCHEMA,
    SPECIALIST_REQUIRED_OUTPUT_PATHS,
    deterministic_expert_registry,
    evaluate_specialist_cascade,
    specialist_cascade_template,
    specialist_lane_proof_from_route_receipt,
    specialist_lane_proof_from_warm_policy,
    specialist_output_template,
    specialist_registry_payload,
    summarize_specialist_cascade,
    validate_specialist_output,
)


EXPECTED_PRODUCTION_LANES = {
    "receipt_auditor",
    "tool_call_risk_classifier",
    "difficulty_estimator",
    "regret_predictor",
    "browser_trace_compressor",
    "screenshot_state_classifier",
    "non_answer_detector",
    "patch_blast_radius_estimator",
    "memory_write_gate",
    "local_hallucination_firewall",
}

EXPECTED_DETERMINISTIC_EXPERTS = {
    "codeql",
    "semgrep",
    "gitleaks",
    "trufflehog",
    "syft",
    "grype",
    "osv_scanner",
    "xgrammar",
    "pytest",
    "mypy",
    "ruff",
}

EXPECTED_BASE_PRODUCTION_LANES = {
    "receipt_auditor",
    "difficulty_estimator",
    "regret_predictor",
    "non_answer_detector",
}


def _warm_policy_payload():
    return {
        "schema": "norman.norllama.warm-policy.v1",
        "benchmark": {
            "status": "loaded",
            "source": "path",
            "path": "/var/lib/norman/norllama/benchmark_packet.json",
            "generated_at": "2026-07-08T00:00:00Z",
        },
        "route_guardrails": {
            "schema": "norman.norllama.route-guardrail-matrix.v1",
            "lanes": {
                "coder": {
                    "eligible_models": [
                        {
                            "model": "qwen3.6:27b",
                            "target_worker": "spark-151",
                            "action": "keep_warm",
                            "authority": "preflight_or_draft",
                            "benchmark_quality": {
                                "eligible": True,
                                "state": "benchmark_backed",
                                "score": 0.91,
                                "coverage_ratio": 1.0,
                            },
                        }
                    ],
                    "blocked_models": [],
                    "canary_models": [],
                },
                "safety": {
                    "eligible_models": [
                        {
                            "model": "qwen3.6:35b-a3b-q4_K_M",
                            "target_worker": "spark-151",
                            "action": "prefetch",
                            "authority": "preflight_or_draft",
                            "benchmark_quality": {
                                "eligible": True,
                                "state": "benchmark_backed",
                                "score": 0.82,
                                "coverage_ratio": 0.9,
                            },
                        }
                    ],
                    "blocked_models": [],
                    "canary_models": [],
                },
                "gui_ground": {
                    "eligible_models": [],
                    "blocked_models": [
                        {
                            "model": "ServiceNow/GroundNext-7B-V0",
                            "target_worker": "spark-151",
                            "action": "skip_quality_gate",
                            "authority": "blocked",
                            "benchmark_quality": {
                                "eligible": False,
                                "state": "unscored",
                                "reason": "missing lane benchmark",
                            },
                        }
                    ],
                    "canary_models": [],
                },
                "verifier": {
                    "eligible_models": [
                        {
                            "model": "qwen3.5:122b-a10b-q4_K_M",
                            "target_worker": "spark-151",
                            "action": "prefetch",
                            "authority": "preflight_or_draft",
                            "benchmark_quality": {
                                "eligible": True,
                                "state": "benchmark_backed",
                                "score": 0.95,
                                "coverage_ratio": 1.0,
                            },
                        }
                    ],
                    "blocked_models": [],
                    "canary_models": [],
                },
            },
        },
    }


def test_specialist_lane_registry_declares_required_production_gates():
    payload = specialist_registry_payload()
    lanes = {lane["lane"]: lane for lane in payload["lanes"]}

    assert payload["schema"] == SPECIALIST_LANE_REGISTRY_SCHEMA
    assert set(lanes) == EXPECTED_PRODUCTION_LANES
    assert payload["policy"]["older_baseline_defaults_allowed"] is False
    assert {
        lane_name for lane_name, lane in lanes.items() if lane["state"] == "production"
    } == EXPECTED_BASE_PRODUCTION_LANES
    assert {
        lane_name for lane_name, lane in lanes.items() if lane["state"] == "lab"
    } == (EXPECTED_PRODUCTION_LANES - EXPECTED_BASE_PRODUCTION_LANES)

    for lane in lanes.values():
        assert lane["state"] in ALLOWED_SPECIALIST_STATES
        assert "qwen3" in lane["model_floor"].lower()
        assert lane["older_baseline_defaults_allowed"] is False
        assert lane["output_schema"]["schema"] == (
            "norman.norllama.specialist-output.v1"
        )
        for gate in (
            "live_smoke_test",
            "schema_checked_output",
            "benchmark_evidence",
            "route_receipt_fields",
            "worker_attribution",
            "usage_accounting",
            "declared_state",
        ):
            assert lane["gates"][gate]["required"] is True


def test_deterministic_experts_are_registered_in_same_cascade():
    registry = deterministic_expert_registry()
    experts = {expert["expert"]: expert for expert in registry["experts"]}

    assert set(experts) == EXPECTED_DETERMINISTIC_EXPERTS
    for expert in experts.values():
        assert expert["command"]
        assert expert["state"] in ALLOWED_SPECIALIST_STATES
        assert expert["usage_bucket"] == "offline_local"
        assert expert["route_receipt_required"] is True


def test_specialist_output_validator_checks_lane_schema_contracts():
    payload = specialist_registry_payload()
    for lane in payload["lanes"]:
        output = specialist_output_template(lane["lane"])
        result_field = next(
            path
            for path in lane["required_output_paths"]
            if path not in SPECIALIST_REQUIRED_OUTPUT_PATHS
        )
        output.update(
            {
                "verdict": "pass",
                "confidence": 0.9,
                "evidence": [{"id": "smoke"}],
                "schema_valid": True,
                "benchmark_evidence": {
                    "source": "uplink_lane_benchmark",
                    "fresh": True,
                },
                "worker_attribution": {
                    "selected_provider": "norllama",
                    "selected_model": lane["model_floor"],
                    "selected_worker": "spark-150",
                },
            }
        )
        output["usage"]["offline_local"] = 17
        output[result_field] = {"status": "ok"}

        assert validate_specialist_output(lane["lane"], output)["valid"] is True

        missing = dict(output)
        missing.pop("verdict")
        invalid = validate_specialist_output(lane["lane"], missing)
        assert invalid["valid"] is False
        assert "verdict" in invalid["missing_fields"]


def test_specialist_cascade_template_exposes_lanes_experts_and_accounting():
    cascade = specialist_cascade_template(
        phase="plan",
        selected_provider="norllama",
        selected_model="qwen3.6:35b-a3b-q4_K_M",
        selected_worker="spark-151",
        usage_bucket="offline_local",
    )
    summary = summarize_specialist_cascade(cascade)

    assert cascade["schema"] == SPECIALIST_CASCADE_SCHEMA
    assert summary["lane_count"] == 10
    assert summary["expert_count"] == 11
    assert set(summary["lanes"]) == EXPECTED_PRODUCTION_LANES
    assert set(summary["deterministic_experts"]) == EXPECTED_DETERMINISTIC_EXPERTS
    assert set(cascade["usage_accounting"]) == {
        "offline_local",
        "openai_codex",
        "bedrock_amazon",
        "perplexity_web",
        "other_cloud",
    }
    first_lane = cascade["lanes"][0]
    assert first_lane["live_smoke_test_required"] is True
    assert first_lane["schema_checked_output_required"] is True
    assert first_lane["benchmark_evidence_required"] is True
    assert first_lane["worker_attribution_required"] is True
    assert first_lane["proof_state"] == "aspirational"
    assert first_lane["live_smoke_test"]["status"] == "pending"


def test_specialist_lane_proof_resolves_warm_policy_benchmarks():
    proof = specialist_lane_proof_from_warm_policy(_warm_policy_payload())
    lanes = {lane["lane"]: lane for lane in proof["lanes"]}

    assert proof["schema"] == SPECIALIST_PROOF_SCHEMA
    assert proof["production_ready_count"] >= 4
    assert lanes["patch_blast_radius_estimator"]["proof_state"] == "production"
    assert lanes["patch_blast_radius_estimator"]["benchmark_evidence"]["fresh"] is True
    assert lanes["patch_blast_radius_estimator"]["live_smoke_test"]["worker"] == (
        "spark-151"
    )
    assert lanes["screenshot_state_classifier"]["proof_state"] == "lab"
    assert lanes["screenshot_state_classifier"]["live_smoke_test"]["status"] == (
        "blocked"
    )


def test_specialist_lane_proof_can_fall_back_to_route_receipt():
    proof = specialist_lane_proof_from_route_receipt(
        {
            "selected_model": "qwen3.6:27b",
            "selected_worker": "spark-151",
            "benchmark_packet_id": "uplink-1",
            "benchmark_fresh": True,
            "benchmark_score": 0.91,
            "coverage_ratio": 1.0,
            "task_kind": "code",
            "route_reason": "benchmark backed",
        }
    )

    assert proof["schema"] == SPECIALIST_PROOF_SCHEMA
    assert proof["by_state"]["production"] == 4
    assert proof["by_state"]["lab"] == 6
    lane = next(
        item for item in proof["lanes"] if item["lane"] == "tool_call_risk_classifier"
    )
    assert lane["proof_state"] == "lab"
    assert lane["live_smoke_test"]["status"] == "receipt_only"
    assert lane["benchmark_evidence"]["fresh"] is True


def test_specialist_cascade_evaluator_runs_deterministic_receipt_checks():
    route_receipt = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": "req-1",
        "job_id": "job-1",
        "phase": "plan",
        "task_kind": "plan",
        "selected_provider": "norllama",
        "selected_model": "qwen3.6:35b-a3b-q4_K_M",
        "target_model": "qwen3.6:35b-a3b-q4_K_M",
        "effective_runtime_model": "qwen3.6:35b-a3b-q4_K_M",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "observed_worker": "spark-151",
        "frontdoor": "https://llm.home.arpa",
        "peer_path": ["https://llm.home.arpa", "spark-151"],
        "route_reason": "local first",
        "policy_mode": "local_first",
        "cloud_proxy": False,
        "benchmark_packet_id": "uplink-1",
        "benchmark_fresh": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 1.0,
        "input_tokens": 10,
        "output_tokens": 0,
        "total_tokens": 10,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": None,
        "verifier_result": "skipped",
        "output_shape": "empty",
    }
    cascade = evaluate_specialist_cascade(
        specialist_cascade_template(
            phase="plan",
            selected_provider="norllama",
            selected_model="qwen3.6:35b-a3b-q4_K_M",
            selected_worker="spark-151",
        ),
        route_receipt=route_receipt,
        output={},
        metadata={"warm_policy": _warm_policy_payload()},
    )
    lanes = {lane["lane"]: lane for lane in cascade["lanes"]}

    assert cascade["status"] == "evaluated"
    assert lanes["receipt_auditor"]["status"] == "fail"
    assert lanes["receipt_auditor"]["result"]["status"] == "fail"
    assert lanes["receipt_auditor"]["result"]["failures"]
    assert lanes["non_answer_detector"]["status"] == "fail"
    assert lanes["difficulty_estimator"]["verdict"] == "low"
    assert lanes["regret_predictor"]["verdict"] == "high"
    assert lanes["browser_trace_compressor"]["status"] == "skipped_no_input"
    assert lanes["patch_blast_radius_estimator"]["proof_state"] == "production"
    assert lanes["patch_blast_radius_estimator"]["benchmark_evidence"]["fresh"] is True
    assert lanes["screenshot_state_classifier"]["proof_state"] == "lab"
    assert cascade["specialist_lane_proof"]["schema"] == SPECIALIST_PROOF_SCHEMA
    assert cascade["summary"]["lane_count"] == 10
    assert cascade["summary"]["benchmark_fresh_count"] >= 4


def test_specialist_non_answer_detector_rejects_plan_only_and_unknown_shapes():
    for output_shape in ("plan_only", "unknown"):
        route_receipt = {
            "status": "completed",
            "request_id": f"req-{output_shape}",
            "job_id": f"job-{output_shape}",
            "phase": "verify",
            "task_kind": "verify",
            "selected_provider": "norllama",
            "selected_model": "qwen3.6:35b-a3b-q4_K_M",
            "target_model": "qwen3.6:35b-a3b-q4_K_M",
            "effective_runtime_model": "qwen3.6:35b-a3b-q4_K_M",
            "selected_worker": "spark-151",
            "observed_worker": "spark-151",
            "observed_worker_source": "gateway_response",
            "frontdoor": "https://llm.home.arpa",
            "peer_path": ["https://llm.home.arpa", "spark-151"],
            "route_reason": "local first",
            "policy_mode": "local_first",
            "cloud_proxy": False,
            "benchmark_packet_id": "uplink-1",
            "benchmark_source": "uplink_benchmark",
            "benchmark_gate": "production",
            "promotion_authoritative": True,
            "benchmark_fresh": True,
            "benchmark_score": 0.91,
            "coverage_ratio": 1.0,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "usage_bucket": "offline_local",
            "fallback_used": False,
            "fallback_reason": None,
            "verifier_result": "pass",
            "output_shape": output_shape,
        }

        cascade = evaluate_specialist_cascade(
            specialist_cascade_template(
                phase="verify",
                selected_provider="norllama",
                selected_model="qwen3.6:35b-a3b-q4_K_M",
                selected_worker="spark-151",
            ),
            route_receipt=route_receipt,
        )
        lanes = {lane["lane"]: lane for lane in cascade["lanes"]}

        assert lanes["non_answer_detector"]["status"] == "fail"
        assert lanes["non_answer_detector"]["verdict"] == output_shape


def test_specialist_cascade_records_executed_deterministic_expert_results(monkeypatch):
    monkeypatch.setattr(
        specialist_lanes.shutil,
        "which",
        lambda command: "/usr/bin/ruff" if command == "ruff" else None,
    )
    route_receipt = {
        "request_id": "req-expert",
        "job_id": "job-expert",
        "phase": "verify",
        "task_kind": "verify",
        "selected_provider": "norllama",
        "selected_model": "qwen3.6:35b-a3b-q4_K_M",
        "target_model": "qwen3.6:35b-a3b-q4_K_M",
        "effective_runtime_model": "qwen3.6:35b-a3b-q4_K_M",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "observed_worker": "spark-151",
        "frontdoor": "https://llm.home.arpa",
        "peer_path": ["https://llm.home.arpa", "spark-151"],
        "route_reason": "local first",
        "policy_mode": "local_first",
        "cloud_proxy": False,
        "benchmark_packet_id": "uplink-1",
        "benchmark_fresh": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 1.0,
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": None,
        "verifier_result": "pass",
        "output_shape": "complete",
    }
    cascade = specialist_cascade_template(
        phase="verify",
        selected_provider="norllama",
        selected_model="qwen3.6:35b-a3b-q4_K_M",
        selected_worker="spark-151",
        deterministic_experts=["ruff"],
    )

    evaluated = evaluate_specialist_cascade(
        cascade,
        route_receipt=route_receipt,
        metadata={
            "deterministic_expert_results": {
                "ruff": {"ok": True, "returncode": 0, "summary": "clean"}
            }
        },
    )
    experts = {item["expert"]: item for item in evaluated["deterministic_experts"]}

    assert experts["ruff"]["status"] == "pass"
    assert experts["ruff"]["execution_mode"] == "executed"
    assert experts["ruff"]["result"]["summary"] == "clean"
    assert all(
        item["status"] != "available_not_run"
        for item in evaluated["deterministic_experts"]
    )
