from __future__ import annotations

from app.services.norllama.fast_lane_outcomes import (
    FAST_LANE_OUTCOME_SCHEMA,
    classify_fast_lane_contract,
    evaluate_fast_lane_outcome,
    summarize_fast_lane_outcomes,
)


def _luna_receipt(**overrides):
    return {
        "selected_provider": "codex",
        "selected_model": "openai.gpt-5.6-luna",
        "effective_model": "openai.gpt-5.6-luna",
        "cloud_proxy": True,
        "validator_gate": "pass",
        "validator_passed": True,
        "estimated_cost_usd": 0.004,
        "baseline_all_5_5_cost_usd": 0.02,
        "input_tokens": 1_000,
        "output_tokens": 500,
        "latency_ms": 220,
        **overrides,
    }


def _local_receipt(**overrides):
    return {
        "selected_provider": "norllama",
        "selected_model": "qwen3.6:27b",
        "cloud_proxy": False,
        "usage_bucket": "offline_local",
        "verifier_result": "pass",
        "input_tokens": 1_000,
        "output_tokens": 500,
        "completion_ms": 180,
        "capacity_evidence": {
            "state": "ready",
            "target_worker_reachable": True,
            "target_active": True,
        },
        **overrides,
    }


def test_verified_luna_tui_receipt_has_material_savings() -> None:
    outcome = evaluate_fast_lane_outcome(_luna_receipt())

    assert outcome["schema"] == FAST_LANE_OUTCOME_SCHEMA
    assert outcome["state"] == "verified"
    assert outcome["lane"]["kind"] == "luna"
    assert outcome["performance"]["savings_usd"] == 0.016
    assert outcome["performance"]["latency_ms"] == 220


def test_verified_local_runtime_receipt_requires_pool_readiness() -> None:
    receipt = _local_receipt(selected_worker="pool-member-a", observed_worker="other")
    outcome = evaluate_fast_lane_outcome(receipt, audit={"pass": True})

    assert outcome["state"] == "verified"
    assert outcome["lane"]["kind"] == "local"
    assert outcome["performance"]["estimated_basis"] == "estimated_not_invoiced"
    assert outcome["task_contract"]["write_mode"] == "not_declared"


def test_retry_or_fallback_is_recorded_as_recovered() -> None:
    outcome = evaluate_fast_lane_outcome(
        _luna_receipt(fallback_used=True, retry_count=1)
    )

    assert outcome["state"] == "recovered"
    assert outcome["reason_codes"] == ["recovery_or_override"]


def test_live_write_authority_boundary_requires_review() -> None:
    outcome = evaluate_fast_lane_outcome(
        _luna_receipt(live_write_attempted=True),
        task_contract={
            "authority_flags": {"delegated_subtask": True, "write_mode": "read_write"}
        },
    )

    assert outcome["state"] == "review_required"
    assert "write_boundary" in outcome["reason_codes"]
    assert "delegated_write_mode" in outcome["reason_codes"]


def test_failed_validation_requires_review() -> None:
    outcome = evaluate_fast_lane_outcome(
        _local_receipt(verifier_result="fail"), audit={"pass": False}
    )

    assert outcome["state"] == "review_required"
    assert outcome["reason_codes"] == ["validation_not_proven"]


def test_insufficient_savings_requires_review() -> None:
    outcome = evaluate_fast_lane_outcome(
        _luna_receipt(
            estimated_cost_usd=0.0195,
            baseline_all_5_5_cost_usd=0.02,
        )
    )

    assert outcome["state"] == "review_required"
    assert outcome["reason_codes"] == ["savings_not_material"]


def test_local_receipt_without_readiness_remains_candidate() -> None:
    outcome = evaluate_fast_lane_outcome(
        _local_receipt(capacity_evidence={}), audit={"pass": True}
    )

    assert outcome["state"] == "candidate"
    assert outcome["reason_codes"] == ["local_readiness_not_proven"]


def test_fast_lane_classification_does_not_depend_on_worker_identity() -> None:
    receipt = _local_receipt(
        selected_worker="spark-151",
        observed_worker="spark-150",
        target_worker="spark-149",
    )

    classification = classify_fast_lane_contract(receipt)

    assert classification["eligible"] is True
    assert classification["lane"] == {
        "kind": "local",
        "provider": "norllama",
        "model": "qwen3.6:27b",
        "cloud_proxy": False,
    }


def test_fast_lane_summary_is_evidence_backed_and_topology_free() -> None:
    verified_luna = evaluate_fast_lane_outcome(_luna_receipt())
    verified_local = evaluate_fast_lane_outcome(_local_receipt(), audit={"pass": True})
    recovered = evaluate_fast_lane_outcome(_luna_receipt(retry_count=1))
    review_required = evaluate_fast_lane_outcome(
        _luna_receipt(live_write_attempted=True)
    )
    candidate = evaluate_fast_lane_outcome(
        _local_receipt(capacity_evidence={}), audit={"pass": True}
    )

    summary = summarize_fast_lane_outcomes(
        [
            {"fast_lane_outcome": verified_luna, "selected_worker": "pool-member-a"},
            {"fast_lane_outcome": verified_local, "selected_worker": "pool-member-b"},
            {"fast_lane_outcome": recovered, "selected_worker": "pool-member-a"},
            {"fast_lane_outcome": review_required, "selected_worker": "pool-member-c"},
            {"fast_lane_outcome": candidate, "selected_worker": "pool-member-b"},
            {"unrelated": "receipt without outcome"},
        ]
    )

    assert summary["schema"] == "norman.fast-lane-outcome-summary.v1"
    assert summary["receipt_count"] == 6
    assert summary["outcome_count"] == 5
    assert summary["eligible_count"] == 5
    assert summary["states"] == {
        "verified": 2,
        "candidate": 1,
        "review_required": 1,
        "recovered": 1,
    }
    assert summary["lanes"]["luna"]["states"] == {
        "verified": 1,
        "candidate": 0,
        "review_required": 1,
        "recovered": 1,
    }
    assert summary["lanes"]["local"]["states"] == {
        "verified": 1,
        "candidate": 1,
        "review_required": 0,
        "recovered": 0,
    }
    assert summary["verified"] == {
        "count": 2,
        "estimated_savings_usd": 0.036,
        "luna_estimated_savings_usd": 0.016,
        "local_not_invoiced_estimated_savings_usd": 0.02,
    }
    assert summary["performance"] == {
        "verified_latency_count": 2,
        "average_verified_latency_ms": 200,
        "median_verified_latency_ms": 200,
    }
    assert {item["code"]: item["count"] for item in summary["reason_codes"]} == {
        "local_readiness_not_proven": 1,
        "recovery_or_override": 1,
        "write_boundary": 1,
    }
    assert summary["calibration"]["auto_selection_enabled"] is False
    assert summary["calibration"]["proof_ready_lanes"] == []
    assert all(
        forbidden not in str(summary)
        for forbidden in (
            "selected_worker",
            "pool-member",
            "endpoint",
            "spark-",
        )
    )


def test_fast_lane_calibration_requires_explicit_enable_after_proof() -> None:
    summary = summarize_fast_lane_outcomes(
        [
            {"fast_lane_outcome": evaluate_fast_lane_outcome(_luna_receipt())}
            for _ in range(12)
        ]
    )

    luna = summary["calibration"]["by_lane"]["luna"]

    assert luna["state"] == "proof_ready"
    assert luna["proactive_eligible"] is True
    assert luna["auto_selection_enabled"] is False
    assert luna["requires_explicit_policy_enable"] is True
    assert summary["calibration"]["proof_ready_lanes"] == ["luna"]
