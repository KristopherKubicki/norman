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
EXPECTED_DETERMINISTIC_LANES = {
    "receipt_auditor",
    "difficulty_estimator",
    "regret_predictor",
    "non_answer_detector",
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

    for lane in lanes.values():
        assert lane["state"] in ALLOWED_SPECIALIST_STATES
        if lane["lane"] in EXPECTED_DETERMINISTIC_LANES:
            assert lane["state"] == "production"
        else:
            assert lane["state"] == "lab"
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
    assert lane["live_smoke_test"]["status"] == "receipt_only"
    assert lane["benchmark_evidence"]["fresh"] is True


def test_specialist_cascade_evaluator_runs_deterministic_receipt_checks():
    route_receipt = {
        "schema": "norman.norllama.route-receipt.v1",
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
    assert lanes["receipt_auditor"]["status"] == "pass"
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
