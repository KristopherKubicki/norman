"""Evaluate proof-backed fast-lane outcomes without exposing pool internals."""

from __future__ import annotations

from typing import Any, Iterable

from app.services.norllama.route_proof import GOOD_VERIFIER_RESULTS

FAST_LANE_OUTCOME_SCHEMA = "norman.fast-lane-outcome.v1"
FAST_LANE_OUTCOME_SUMMARY_SCHEMA = "norman.fast-lane-outcome-summary.v1"
LOCAL_PROVIDERS = {"norllama", "ollama", "local_ollama", "local-ollama"}
LOCAL_USAGE_BUCKETS = {"offline_local", "offline"}
LOCAL_READY_STATES = {"available", "ready"}
SAFE_MUTATION_RISKS = {"", "0", "false", "none", "read_only", "read-only"}
LUNA_RATE_PER_MILLION = {"input": 1.0, "cached_input": 0.10, "output": 6.0}
TERRA_RATE_PER_MILLION = {"input": 5.0, "cached_input": 0.50, "output": 30.0}
MINIMUM_SAVINGS_USD = 0.001
MINIMUM_SAVINGS_RATIO = 0.20
FAST_LANE_KINDS = ("luna", "local")
FAST_LANE_STATES = ("verified", "candidate", "review_required", "recovered")
FAST_LANE_CALIBRATION_MIN_VERIFIED = 12
FAST_LANE_CALIBRATION_MIN_VERIFICATION_RATIO = 0.90
FAST_LANE_CALIBRATION_MAX_RECOVERY_RATIO = 0.05


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    value = _lower(value)
    if value in {"1", "true", "yes", "on", "enabled", "required"}:
        return True
    if value in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _first_text(receipt: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = _clean(receipt.get(field))
        if value:
            return value
    return ""


def _first_dict(receipt: dict[str, Any], *fields: str) -> dict[str, Any]:
    for field in fields:
        value = receipt.get(field)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _model_matches_luna(receipt: dict[str, Any]) -> str:
    for field in (
        "effective_runtime_model",
        "effective_model",
        "selected_model",
        "route_selected_model",
        "target_model",
        "requested_model",
    ):
        model = _clean(receipt.get(field))
        if "gpt-5.6-luna" in model.lower():
            return model
    return ""


def _local_route(receipt: dict[str, Any]) -> bool:
    provider = _lower(
        _first_text(receipt, "selected_provider", "effective_provider", "provider")
    )
    usage_bucket = _lower(receipt.get("usage_bucket"))
    return not _flag(receipt.get("cloud_proxy")) and (
        provider in LOCAL_PROVIDERS or usage_bucket in LOCAL_USAGE_BUCKETS
    )


def classify_fast_lane_contract(
    receipt: dict[str, Any] | None,
    task_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify whether a receipt used a supported fast lane."""

    del task_contract
    clean_receipt = dict(receipt or {})
    luna_model = _model_matches_luna(clean_receipt)
    provider = _first_text(
        clean_receipt, "selected_provider", "effective_provider", "provider"
    )
    model = luna_model or _first_text(
        clean_receipt,
        "effective_runtime_model",
        "effective_model",
        "selected_model",
        "target_model",
        "requested_model",
    )
    lane_kind = "luna" if luna_model else "local" if _local_route(clean_receipt) else ""
    return {
        "eligible": bool(lane_kind),
        "lane": {
            "kind": lane_kind or "none",
            "provider": provider,
            "model": model,
            "cloud_proxy": _flag(clean_receipt.get("cloud_proxy")),
        },
    }


def _readiness(receipt: dict[str, Any], local_lane: bool) -> dict[str, Any]:
    if not local_lane:
        return {"required": False, "passed": True, "state": "not_applicable"}
    capacity = _first_dict(receipt, "capacity_evidence")
    state = _lower(capacity.get("state") or receipt.get("capacity_state"))
    reachable = _flag(
        capacity.get("target_worker_reachable", receipt.get("target_worker_reachable"))
    )
    active = _flag(capacity.get("target_active", receipt.get("target_active")))
    passed = state in LOCAL_READY_STATES and reachable and active
    return {
        "required": True,
        "passed": passed,
        "state": state or "missing",
        "target_reachable": reachable,
        "target_active": active,
    }


def _contract_sources(task_contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    contract = dict(task_contract or {})
    sources = [contract]
    for field in ("authority_flags", "route_policy", "metadata"):
        value = contract.get(field)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _source_flag(sources: list[dict[str, Any]], *fields: str) -> bool:
    return any(_flag(source.get(field)) for source in sources for field in fields)


def _authority(
    receipt: dict[str, Any], contract: dict[str, Any] | None
) -> dict[str, Any]:
    sources = [receipt, *_contract_sources(contract)]
    mutation_risk = _lower(receipt.get("mutation_risk"))
    if mutation_risk in SAFE_MUTATION_RISKS:
        mutation_risk = ""
    approval_list = (
        contract.get("approval_required_for")
        if isinstance(contract, dict)
        and isinstance(contract.get("approval_required_for"), list)
        else []
    )
    delegated = _source_flag(sources, "delegated_subtask", "is_delegated")
    write_mode = next(
        (
            _lower(source.get("write_mode"))
            for source in sources
            if _clean(source.get("write_mode"))
        ),
        "",
    )
    reasons: list[str] = []
    if mutation_risk:
        reasons.append("mutation_risk")
    if _source_flag(sources, "manual_override", "model_override_used"):
        reasons.append("manual_override")
    if _source_flag(sources, "boundary_violation", "live_write_attempted"):
        reasons.append("write_boundary")
    if approval_list or _source_flag(sources, "operator_approval_required"):
        reasons.append("operator_approval")
    if _source_flag(sources, "final_authority_required"):
        reasons.append("final_authority")
    if _lower(receipt.get("authority_class")) == "final_authority":
        reasons.append("final_authority")
    if delegated and write_mode != "read_only":
        reasons.append("delegated_write_mode")
    return {
        "passed": not reasons,
        "delegated": delegated,
        "write_mode": write_mode or "not_declared",
        "reason_codes": sorted(set(reasons)),
    }


def _validation(
    receipt: dict[str, Any], audit: dict[str, Any] | None
) -> dict[str, Any]:
    tui_receipt = "validator_gate" in receipt or "validator_passed" in receipt
    if tui_receipt:
        passed = (
            _lower(receipt.get("validator_gate")) == "pass"
            and receipt.get("validator_passed") is True
        )
        return {
            "source": "tui_validator",
            "passed": passed,
            "verifier_result": _lower(receipt.get("validator_gate")),
        }
    receipt_audit = (
        audit if isinstance(audit, dict) else _first_dict(receipt, "receipt_audit")
    )
    verifier = _lower(receipt.get("verifier_result"))
    passed = verifier in GOOD_VERIFIER_RESULTS and receipt_audit.get("pass") is True
    return {
        "source": "route_receipt_audit",
        "passed": passed,
        "verifier_result": verifier or "missing",
        "audit_passed": receipt_audit.get("pass") is True,
    }


def _token_cost(receipt: dict[str, Any], rates: dict[str, float]) -> float:
    input_tokens = _number(receipt.get("input_tokens"))
    cached_tokens = _number(receipt.get("cached_input_tokens"))
    output_tokens = _number(receipt.get("output_tokens"))
    return (
        input_tokens * rates["input"]
        + cached_tokens * rates["cached_input"]
        + output_tokens * rates["output"]
    ) / 1_000_000


def _savings(receipt: dict[str, Any], lane_kind: str) -> dict[str, Any]:
    baseline = _number(receipt.get("baseline_all_terra_cost_usd"))
    if baseline <= 0:
        baseline = _number(receipt.get("baseline_all_5_5_cost_usd"))
    if baseline <= 0:
        baseline = _token_cost(receipt, TERRA_RATE_PER_MILLION)
    estimated = _number(receipt.get("estimated_cost_usd"))
    estimated_basis = "receipt"
    if lane_kind == "local":
        estimated, estimated_basis = 0.0, "estimated_not_invoiced"
    elif "estimated_cost_usd" not in receipt:
        estimated, estimated_basis = _token_cost(receipt, LUNA_RATE_PER_MILLION), "rate"
    savings_usd = max(0.0, baseline - estimated)
    savings_ratio = savings_usd / baseline if baseline else 0.0
    return {
        "passed": savings_usd >= MINIMUM_SAVINGS_USD
        and savings_ratio >= MINIMUM_SAVINGS_RATIO,
        "estimated_cost_usd": round(estimated, 6),
        "baseline_cost_usd": round(baseline, 6),
        "savings_usd": round(savings_usd, 6),
        "savings_ratio": round(savings_ratio, 4),
        "estimated_basis": estimated_basis,
    }


def _recovery(receipt: dict[str, Any]) -> dict[str, Any]:
    attempts = receipt.get("attempts")
    attempts_count = len(attempts) if isinstance(attempts, list) else 0
    recovered = (
        _flag(receipt.get("fallback_used"))
        or _number(receipt.get("retry_count")) > 0
        or _number(receipt.get("timeout_count")) > 0
        or attempts_count > 1
        or _flag(receipt.get("manual_override"))
        or _flag(receipt.get("model_override_used"))
    )
    return {"recovered": recovered, "attempt_count": attempts_count}


def _outcome_state(
    classification: dict[str, Any],
    readiness: dict[str, Any],
    authority: dict[str, Any],
    validation: dict[str, Any],
    savings: dict[str, Any],
    recovery: dict[str, Any],
) -> tuple[str, list[str]]:
    if recovery["recovered"]:
        return "recovered", ["recovery_or_override"]
    if not classification["eligible"]:
        return "candidate", ["not_fast_lane"]
    if not authority["passed"]:
        return "review_required", authority["reason_codes"]
    if not validation["passed"]:
        return "review_required", ["validation_not_proven"]
    if not savings["passed"]:
        return "review_required", ["savings_not_material"]
    if not readiness["passed"]:
        return "candidate", ["local_readiness_not_proven"]
    return "verified", []


def evaluate_fast_lane_outcome(
    receipt: dict[str, Any] | None,
    task_contract: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a proof-backed fast-lane outcome for a completed receipt."""

    clean_receipt = dict(receipt or {})
    classification = classify_fast_lane_contract(clean_receipt, task_contract)
    readiness = _readiness(clean_receipt, classification["lane"]["kind"] == "local")
    authority = _authority(clean_receipt, task_contract)
    validation = _validation(clean_receipt, audit)
    savings = _savings(clean_receipt, classification["lane"]["kind"])
    recovery = _recovery(clean_receipt)
    state, reason_codes = _outcome_state(
        classification, readiness, authority, validation, savings, recovery
    )
    latency_ms = int(
        _number(clean_receipt.get("latency_ms") or clean_receipt.get("completion_ms"))
    )
    confidence = {
        "verified": 1.0,
        "recovered": 0.7,
        "candidate": 0.45,
        "review_required": 0.1,
    }[state]
    return {
        "schema": FAST_LANE_OUTCOME_SCHEMA,
        "state": state,
        "eligible": classification["eligible"],
        "lane": classification["lane"],
        "task_contract": authority,
        "validation": validation,
        "performance": {**savings, "latency_ms": latency_ms},
        "reason_codes": reason_codes,
        "confidence": confidence,
    }


def _summary_state_counts() -> dict[str, int]:
    return {state: 0 for state in FAST_LANE_STATES}


def _summary_lane_counts() -> dict[str, dict[str, Any]]:
    return {
        lane: {
            "eligible_count": 0,
            "states": _summary_state_counts(),
        }
        for lane in FAST_LANE_KINDS
    }


def _calibration_summary(
    *,
    eligible_count: int,
    states: dict[str, int],
) -> dict[str, Any]:
    verified_count = int(states.get("verified") or 0)
    recovered_count = int(states.get("recovered") or 0)
    review_count = int(states.get("review_required") or 0)
    verification_ratio = verified_count / eligible_count if eligible_count else 0.0
    recovery_ratio = recovered_count / eligible_count if eligible_count else 0.0
    blockers: list[str] = []
    if verified_count < FAST_LANE_CALIBRATION_MIN_VERIFIED:
        blockers.append("insufficient_verified_samples")
    if verification_ratio < FAST_LANE_CALIBRATION_MIN_VERIFICATION_RATIO:
        blockers.append("verification_rate_below_target")
    if recovery_ratio > FAST_LANE_CALIBRATION_MAX_RECOVERY_RATIO:
        blockers.append("recovery_rate_above_target")
    if review_count:
        blockers.append("review_required_present")
    proof_ready = not blockers
    return {
        "state": "proof_ready" if proof_ready else "calibrating",
        "proactive_eligible": proof_ready,
        "auto_selection_enabled": False,
        "requires_explicit_policy_enable": True,
        "verified_count": verified_count,
        "eligible_count": eligible_count,
        "verification_ratio": round(verification_ratio, 4),
        "recovery_ratio": round(recovery_ratio, 4),
        "minimum_verified_count": FAST_LANE_CALIBRATION_MIN_VERIFIED,
        "minimum_verification_ratio": FAST_LANE_CALIBRATION_MIN_VERIFICATION_RATIO,
        "maximum_recovery_ratio": FAST_LANE_CALIBRATION_MAX_RECOVERY_RATIO,
        "blockers": blockers,
    }


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2)


def summarize_fast_lane_outcomes(
    receipts: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize bounded receipt evidence without exposing pool topology.

    A proof-ready calibration result is evidence for a future explicit policy
    change only. This function never enables route selection by itself.
    """

    states = _summary_state_counts()
    lanes = _summary_lane_counts()
    receipt_count = 0
    outcome_count = 0
    eligible_count = 0
    verified_savings_usd = 0.0
    verified_luna_savings_usd = 0.0
    verified_local_not_invoiced_savings_usd = 0.0
    verified_latencies: list[int] = []
    reason_counts: dict[str, int] = {}

    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        receipt_count += 1
        outcome = receipt.get("fast_lane_outcome")
        if (
            not isinstance(outcome, dict)
            or outcome.get("schema") != FAST_LANE_OUTCOME_SCHEMA
        ):
            continue
        outcome_count += 1
        lane = outcome.get("lane") if isinstance(outcome.get("lane"), dict) else {}
        lane_kind = _lower(lane.get("kind"))
        state = _lower(outcome.get("state"))
        if (
            lane_kind not in FAST_LANE_KINDS
            or state not in FAST_LANE_STATES
            or not _flag(outcome.get("eligible"))
        ):
            continue

        eligible_count += 1
        states[state] += 1
        lanes[lane_kind]["eligible_count"] += 1
        lanes[lane_kind]["states"][state] += 1
        if state == "verified":
            performance = (
                outcome.get("performance")
                if isinstance(outcome.get("performance"), dict)
                else {}
            )
            savings_usd = _number(performance.get("savings_usd"))
            verified_savings_usd += savings_usd
            if lane_kind == "local":
                verified_local_not_invoiced_savings_usd += savings_usd
            else:
                verified_luna_savings_usd += savings_usd
            latency_ms = int(_number(performance.get("latency_ms")))
            if latency_ms:
                verified_latencies.append(latency_ms)
            continue

        raw_reasons = outcome.get("reason_codes")
        if not isinstance(raw_reasons, list):
            continue
        for raw_reason in raw_reasons:
            reason = _lower(raw_reason)
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    calibration_by_lane = {
        lane: _calibration_summary(
            eligible_count=lanes[lane]["eligible_count"],
            states=lanes[lane]["states"],
        )
        for lane in FAST_LANE_KINDS
    }
    proof_ready_lanes = [
        lane
        for lane in FAST_LANE_KINDS
        if calibration_by_lane[lane]["proactive_eligible"]
    ]
    return {
        "schema": FAST_LANE_OUTCOME_SUMMARY_SCHEMA,
        "receipt_count": receipt_count,
        "outcome_count": outcome_count,
        "eligible_count": eligible_count,
        "ignored_count": outcome_count - eligible_count,
        "states": states,
        "lanes": lanes,
        "verified": {
            "count": states["verified"],
            "estimated_savings_usd": round(verified_savings_usd, 6),
            "luna_estimated_savings_usd": round(verified_luna_savings_usd, 6),
            "local_not_invoiced_estimated_savings_usd": round(
                verified_local_not_invoiced_savings_usd, 6
            ),
        },
        "performance": {
            "verified_latency_count": len(verified_latencies),
            "average_verified_latency_ms": round(
                sum(verified_latencies) / len(verified_latencies)
            )
            if verified_latencies
            else 0,
            "median_verified_latency_ms": _median(verified_latencies),
        },
        "reason_codes": [
            {"code": reason, "count": count}
            for reason, count in sorted(
                reason_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "calibration": {
            "auto_selection_enabled": False,
            "requires_explicit_policy_enable": True,
            "proof_ready_lanes": proof_ready_lanes,
            "by_lane": calibration_by_lane,
        },
    }
