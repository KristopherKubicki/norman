from __future__ import annotations

import copy

import pytest

from app.services.norllama.route_proof import (
    audit_route_receipt,
    normalize_route_receipt_for_completion_gate,
    receipt_completion_gate_passes,
)
from app.services.norllama.route_policy import route_policy_contract


def _base_receipt() -> dict[str, object]:
    policy = route_policy_contract()
    return {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": "req-proof",
        "job_id": "job-proof",
        "phase": "verify",
        "task_kind": "verify",
        "selected_provider": "norllama",
        "selected_model": "qwen3.6:27b",
        "route_selected_model": "qwen3.6:27b",
        "requested_model": "qwen3.6:27b",
        "target_model": "qwen3.6:27b",
        "effective_runtime_model": "qwen3.6:27b",
        "model_override_used": False,
        "model_override_reason": "",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "route_attribution_source": "gateway_response",
        "routing_scope": "frontdoor_worker",
        "frontdoor": "https://llm.home.arpa/v1",
        "peer_path": ["https://llm.home.arpa/v1", "spark-151"],
        "route_reason": "local first",
        "policy_mode": "local_first",
        "policy_id": policy["policy_id"],
        "policy_hash": policy["policy_hash"],
        "policy_integrity_valid": True,
        "policy_lifecycle_state": "valid",
        "policy_default_route_allowed": True,
        "policy_issued_at": policy["issued_at"],
        "policy_expires_at": policy["expires_at"],
        "policy_refresh_generation": policy["refresh_generation"],
        "manual_degraded_authorized": False,
        "cloud_proxy": False,
        "benchmark_packet_id": "uplink-route-proof-1",
        "benchmark_source": "uplink_benchmark",
        "benchmark_fresh": True,
        "benchmark_gate": {
            "gate": "production",
            "promotion_authoritative": True,
        },
        "promotion_authoritative": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 0.88,
        "capability_gate_exemption": {
            "exemption_id": "low_risk_local_text_non_mutating",
            "scope": "request",
            "allowed_task_risk": ["low"],
            "mutation_allowed": False,
            "external_side_effects_allowed": False,
            "cloud_allowed": False,
            "requires_transport_gate": "production",
            "reason": "low-risk local text route",
        },
        "capability_gate_exemption_id": "low_risk_local_text_non_mutating",
        "input_tokens": 12,
        "output_tokens": 7,
        "total_tokens": 19,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": None,
        "verifier_result": "pass",
        "output_shape": "complete",
        "completion_requested": True,
        "require_verifier_for_completion": True,
    }


def test_route_receipt_audit_passes_complete_benchmark_backed_local_receipt():
    receipt = _base_receipt()
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True
    assert receipt_completion_gate_passes(receipt, audit=audit, require_verifier=True)


def test_route_receipt_audit_rejects_unknown_status_values():
    receipt = _base_receipt()
    receipt["status"] = "mystery"

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "invalid_status:mystery" in audit["failures"]


@pytest.mark.parametrize("shape", ["", "unknown", "plan_only", "progress_only"])
def test_route_receipt_audit_rejects_non_complete_output_shapes(shape):
    receipt = _base_receipt()
    receipt["output_shape"] = shape

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert (
        receipt_completion_gate_passes(receipt, audit=audit, require_verifier=True)
        is False
    )
    assert any(
        failure.startswith("bad_output_shape:")
        or failure.startswith("invalid_output_shape:")
        for failure in audit["failures"]
    )


def test_route_receipt_audit_requires_observed_worker_for_completed_frontdoor_local():
    receipt = _base_receipt()
    receipt["observed_worker"] = ""

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "empty_critical_field:observed_worker" not in audit["failures"]
    assert "observed_worker_missing_for_frontdoor_route" in audit["failures"]


def test_route_receipt_audit_requires_frontdoor_worker_proof_fields():
    receipt = _base_receipt()
    receipt["selected_worker"] = ""
    receipt["observed_worker"] = ""
    receipt["observed_worker_source"] = "route_hint"
    receipt["peer_path"] = []

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "selected_worker_missing_for_frontdoor_route" in audit["failures"]
    assert "observed_worker_missing_for_frontdoor_route" in audit["failures"]
    assert "observed_worker_source_not_gateway_response" in audit["failures"]
    assert "peer_path_missing_for_frontdoor_route" in audit["failures"]


def test_route_receipt_audit_requires_fallback_reason_for_worker_mismatch():
    receipt = _base_receipt()
    receipt["observed_worker"] = "spark-150"

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "worker_mismatch_without_fallback_used" in audit["failures"]
    assert "worker_mismatch_without_fallback_reason" in audit["failures"]

    receipt["fallback_used"] = True
    receipt["fallback_reason"] = "spark-151 was unavailable; gateway served spark-150"
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True


def test_route_receipt_audit_compares_target_worker_to_observed_worker():
    receipt = _base_receipt()
    receipt["selected_worker"] = "spark-150"
    receipt["target_worker"] = "spark-151"
    receipt["observed_worker"] = "spark-150"

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "worker_mismatch_without_fallback_used" in audit["failures"]

    receipt["fallback_used"] = True
    receipt["fallback_reason"] = "gateway selected spark-150 after spark-151 timeout"
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True


def test_route_receipt_audit_treats_multiple_attempts_as_fallback():
    receipt = _base_receipt()
    receipt["attempts"] = [
        "http://192.168.2.151:18151",
        "http://192.168.2.150:18151",
    ]

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "multi_attempt_without_fallback_used" in audit["failures"]

    receipt["fallback_used"] = True
    receipt["fallback_reason"] = "gateway reported multiple worker attempts"
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True


def test_route_receipt_audit_rejects_unexplained_model_mismatch():
    receipt = _base_receipt()
    receipt["effective_runtime_model"] = "qwen3.6:35b-a3b-q4_K_M"

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "effective_model_differs_from_requested_without_reason" in audit["failures"]

    receipt["fallback_used"] = True
    receipt["fallback_reason"] = "gateway substituted qwen3.6:35b after 27b timeout"
    audit = audit_route_receipt(receipt)

    assert (
        "effective_model_differs_from_requested_without_reason" not in audit["failures"]
    )


def test_route_receipt_audit_allows_explicit_operator_model_override():
    receipt = _base_receipt()
    receipt["requested_model"] = "qwen3.6:35b-a3b-q4_K_M"
    receipt["target_model"] = "qwen3.6:35b-a3b-q4_K_M"
    receipt["effective_runtime_model"] = "qwen3.6:35b-a3b-q4_K_M"
    receipt["model_override_used"] = True
    receipt["model_override_reason"] = "operator_route_lock"
    receipt["benchmark_score"] = 0.94
    receipt["coverage_ratio"] = 0.9

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True


def test_route_receipt_audit_enforces_qwen_benchmark_thresholds():
    receipt = _base_receipt()
    receipt["benchmark_score"] = 0.4
    receipt["coverage_ratio"] = 0.2

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "qwen_default_benchmark_score_below_threshold" in audit["failures"]
    assert "qwen_default_benchmark_coverage_below_threshold" in audit["failures"]


def test_route_receipt_audit_requires_production_authoritative_qwen_gate():
    receipt = _base_receipt()
    receipt["benchmark_gate"] = {"gate": "smoke", "promotion_authoritative": False}
    receipt["promotion_authoritative"] = False

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "qwen_default_without_production_benchmark_gate" in audit["failures"]
    assert "qwen_default_without_promotion_authoritative" in audit["failures"]


def test_route_receipt_audit_allows_explicit_nonproduction_qwen_canary():
    receipt = _base_receipt()
    receipt["benchmark_packet_id"] = "capability-suite-hash"
    receipt["benchmark_source"] = "capability_execution_runner"
    receipt["benchmark_gate"] = {"gate": "canary", "promotion_authoritative": False}
    receipt["transport_gate"] = {"gate": "canary", "promotion_authoritative": False}
    receipt["capability_gate"] = {"gate": "canary", "promotion_authoritative": False}
    receipt["promotion_authoritative"] = False
    receipt["capability_promotion_authoritative"] = False
    receipt["production_route_requires_capability_gate"] = True
    receipt["production_route_eligible"] = False

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True
    assert audit["benchmark"]["production_route_eligible"] is False


def test_route_receipt_audit_requires_qwen_capability_gate_when_required():
    receipt = _base_receipt()
    receipt["production_route_requires_capability_gate"] = True
    receipt["capability_gate"] = {
        "gate": "unproven",
        "promotion_authoritative": False,
    }
    receipt["capability_promotion_authoritative"] = False

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "qwen_default_without_production_capability_gate" in audit["failures"]
    assert (
        "qwen_default_without_capability_promotion_authoritative" in audit["failures"]
    )

    receipt["capability_gate"] = {
        "gate": "production",
        "promotion_authoritative": True,
    }
    receipt["capability_promotion_authoritative"] = True
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True
    assert audit["benchmark"]["capability_gate"]["gate"] == "production"


def test_route_receipt_audit_requires_named_capability_exemption_when_not_required():
    receipt = _base_receipt()
    receipt["capability_gate_exemption"] = {}
    receipt["capability_gate_exemption_id"] = ""

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert (
        "qwen_default_capability_gate_not_required_without_exemption"
        in audit["failures"]
    )

    receipt["capability_gate_exemption"] = {
        "exemption_id": "low_risk_local_text_non_mutating"
    }
    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True
    assert (
        audit["benchmark"]["capability_gate_exemption_id"]
        == "low_risk_local_text_non_mutating"
    )


def test_route_receipt_audit_rejects_zero_token_generative_completion():
    receipt = _base_receipt()
    receipt["output_tokens"] = 0
    receipt["total_tokens"] = 12

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "zero_token_generative_completion" in audit["failures"]


def test_route_receipt_audit_validates_json_field_types():
    receipt = _base_receipt()
    receipt["cloud_proxy"] = "false"
    receipt["benchmark_score"] = "0.91"
    receipt["peer_path"] = "llm.home.arpa,spark-151"

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "type_mismatch:cloud_proxy:bool" in audit["failures"]
    assert "type_mismatch:benchmark_score:number" in audit["failures"]
    assert "type_mismatch:peer_path:list" in audit["failures"]


def test_route_receipt_normalizer_runs_before_completion_gate():
    raw = _base_receipt()
    raw["verifier_result"] = "skipped"

    normalized = normalize_route_receipt_for_completion_gate(
        copy.deepcopy(raw),
        verification_signal="complete",
    )
    audit = audit_route_receipt(normalized)

    assert normalized["verifier_result"] == "pass"
    assert audit["pass"] is True
    assert receipt_completion_gate_passes(
        normalized, audit=audit, require_verifier=True
    )


def test_route_receipt_audit_rejects_expired_policy_for_production_completion():
    receipt = _base_receipt()
    receipt["policy_lifecycle_state"] = "expired_blocked"
    receipt["policy_default_route_allowed"] = False

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "policy_lifecycle_not_allowed:expired_blocked" in audit["failures"]
    assert "policy_default_route_not_allowed" in audit["failures"]


def test_route_receipt_audit_rejects_wrong_policy_hash():
    receipt = _base_receipt()
    receipt["policy_hash"] = "0" * 64

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "policy_hash_differs_from_active_authority" in audit["failures"]


def test_route_receipt_records_manual_degraded_authorization():
    receipt = _base_receipt()
    receipt["policy_lifecycle_state"] = "expired_blocked"
    receipt["policy_default_route_allowed"] = False
    receipt["production_route_eligible"] = False
    receipt["manual_degraded_authorized"] = True
    receipt["manual_degraded_authorization"] = {
        "manual_degraded_authorized": True,
        "authorization_id": "manual-1",
        "authorized_by": "operator",
        "authorization_reason": "policy refresh drill",
        "authorization_created_at": "2026-07-13T12:00:00Z",
        "authorization_expires_at": "2026-07-13T13:00:00Z",
        "cloud_allowed": False,
    }

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is True


def test_route_receipt_rejects_manual_degraded_as_production():
    receipt = _base_receipt()
    receipt["manual_degraded_authorized"] = True
    receipt["manual_degraded_authorization"] = {
        "manual_degraded_authorized": True,
        "authorization_id": "manual-1",
        "authorized_by": "operator",
        "authorization_reason": "policy refresh drill",
        "authorization_created_at": "2026-07-13T12:00:00Z",
        "authorization_expires_at": "2026-07-13T13:00:00Z",
        "cloud_allowed": False,
    }

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "manual_degraded_marked_production_eligible" in audit["failures"]
