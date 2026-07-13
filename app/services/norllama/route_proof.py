from __future__ import annotations

from typing import Any

ROUTE_RECEIPT_AUDIT_SCHEMA = "norman.norllama.route-receipt-audit.v1"

REQUIRED_ROUTE_RECEIPT_FIELDS = (
    "status",
    "request_id",
    "job_id",
    "phase",
    "task_kind",
    "selected_provider",
    "selected_model",
    "route_selected_model",
    "requested_model",
    "target_model",
    "effective_runtime_model",
    "model_override_used",
    "model_override_reason",
    "selected_worker",
    "observed_worker",
    "frontdoor",
    "peer_path",
    "route_reason",
    "policy_mode",
    "policy_id",
    "policy_hash",
    "policy_integrity_valid",
    "policy_lifecycle_state",
    "policy_default_route_allowed",
    "policy_issued_at",
    "policy_expires_at",
    "policy_refresh_generation",
    "manual_degraded_authorized",
    "cloud_proxy",
    "benchmark_packet_id",
    "benchmark_fresh",
    "benchmark_score",
    "coverage_ratio",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "usage_bucket",
    "fallback_used",
    "fallback_reason",
    "verifier_result",
    "output_shape",
)

NON_COMPLETION_OUTPUT_SHAPES = {
    "",
    "empty",
    "error",
    "plan_only",
    "progress_only",
    "timeout",
    "unknown",
}
VALID_OUTPUT_SHAPES = NON_COMPLETION_OUTPUT_SHAPES | {"complete"}
VALID_ROUTE_RECEIPT_STATUSES = {
    "blocked",
    "canceled",
    "cancelled",
    "checkpointed",
    "completed",
    "degraded",
    "error",
    "failed",
    "partial",
    "planned",
    "planning",
    "progress",
    "queued",
    "running",
    "skipped",
    "timeout",
    "unavailable",
}
LOCAL_USAGE_BUCKETS = {"offline_local", "offline"}
CLOUD_USAGE_BUCKETS = {
    "openai_codex",
    "bedrock_amazon",
    "other_cloud",
    "cloud_openai",
    "cloud_amazon",
    "cloud_other",
}
GOOD_VERIFIER_RESULTS = {"pass", "passed", "complete", "verified", "ok"}
BAD_VERIFIER_RESULTS = {"fail", "failed", "needs_more_work", "rejected", "error"}
QWEN_PRODUCTION_PREFIXES = (
    "qwen3.6",
    "qwen3.5",
    "nvidia/qwen3.6",
    "nvidia/qwen3.5",
)
UPLINK_BENCHMARK_SOURCES = {"uplink_benchmark", "uplink_lane_benchmark"}
QWEN_PRODUCTION_MIN_BENCHMARK_SCORE = 0.75
QWEN_PRODUCTION_MIN_COVERAGE_RATIO = 0.70
GENERATOR_TASK_KINDS = {
    "chat",
    "code",
    "compact",
    "judge",
    "plan",
    "scout",
    "summarize",
    "verify",
    "world",
}
CRITICAL_STRING_FIELDS = {
    "status",
    "request_id",
    "job_id",
    "phase",
    "task_kind",
    "selected_provider",
    "selected_model",
    "route_selected_model",
    "requested_model",
    "target_model",
    "effective_runtime_model",
    "frontdoor",
    "route_reason",
    "policy_mode",
    "policy_id",
    "policy_hash",
    "policy_lifecycle_state",
    "policy_issued_at",
    "policy_expires_at",
    "usage_bucket",
    "verifier_result",
    "output_shape",
}
STRICT_BOOL_FIELDS = {
    "cloud_proxy",
    "benchmark_fresh",
    "fallback_used",
    "model_override_used",
    "policy_integrity_valid",
    "policy_default_route_allowed",
    "manual_degraded_authorized",
}
STRICT_NUMERIC_FIELDS = {
    "benchmark_score",
    "coverage_ratio",
    "cold_start_ms",
    "first_token_ms",
    "completion_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "policy_refresh_generation",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    clean = _lower(value)
    if not clean:
        return default
    if clean in {"1", "true", "yes", "on", "enabled", "required"}:
        return True
    if clean in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _json_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _json_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_qwen_production_model(model: str) -> bool:
    clean = _lower(model).replace("_", "-")
    return clean.startswith(QWEN_PRODUCTION_PREFIXES)


def _is_generative_receipt(receipt: dict[str, Any]) -> bool:
    task_kind = _lower(receipt.get("task_kind") or receipt.get("phase"))
    if task_kind in GENERATOR_TASK_KINDS:
        return True
    capability = _lower(receipt.get("capability"))
    return capability in GENERATOR_TASK_KINDS


def _normalize_verifier_result(value: Any) -> str:
    clean = _lower(value)
    if clean in GOOD_VERIFIER_RESULTS:
        return "pass"
    if clean in BAD_VERIFIER_RESULTS:
        return "fail"
    if clean in {"skip", "skipped", "not_required", "not-required"}:
        return "skipped"
    return clean or "skipped"


def normalize_route_receipt_for_completion_gate(
    receipt: dict[str, Any] | None,
    *,
    verification_signal: str = "",
) -> dict[str, Any]:
    """Return the exact receipt shape that the completion gate should audit."""

    normalized = dict(receipt or {})
    status = _lower(normalized.get("status"))
    if status:
        normalized["status"] = status
    output_shape = _lower(normalized.get("output_shape"))
    normalized["output_shape"] = output_shape if output_shape else "unknown"
    verifier_result = _normalize_verifier_result(normalized.get("verifier_result"))
    signal = _lower(verification_signal)
    if signal == "complete":
        verifier_result = "pass"
    elif signal == "needs_more_work":
        verifier_result = "fail"
    normalized["verifier_result"] = verifier_result
    return normalized


def _benchmark_source(receipt: dict[str, Any]) -> str:
    quality = {}
    selection = receipt.get("model_selection")
    if isinstance(selection, dict):
        quality = (
            selection.get("benchmark_quality")
            if isinstance(selection.get("benchmark_quality"), dict)
            else {}
        )
    selection_source = selection.get("source") if isinstance(selection, dict) else ""
    return _lower(
        receipt.get("benchmark_source") or quality.get("source") or selection_source
    )


def _benchmark_gate_name(receipt: dict[str, Any]) -> str:
    gate = receipt.get("benchmark_gate")
    if isinstance(gate, dict):
        return _lower(gate.get("gate") or gate.get("name"))
    return _lower(gate)


def _promotion_authoritative(receipt: dict[str, Any]) -> bool:
    if "promotion_authoritative" in receipt:
        return _flag(receipt.get("promotion_authoritative"))
    gate = receipt.get("benchmark_gate")
    if isinstance(gate, dict):
        return _flag(gate.get("promotion_authoritative"))
    selection = receipt.get("model_selection")
    if isinstance(selection, dict):
        quality = selection.get("benchmark_quality")
        if isinstance(quality, dict):
            return _flag(quality.get("promotion_authoritative"))
    return False


def _capability_gate_name(receipt: dict[str, Any]) -> str:
    gate = receipt.get("capability_gate")
    if isinstance(gate, dict):
        return _lower(gate.get("gate") or gate.get("name"))
    return _lower(gate) or "unproven"


def _capability_promotion_authoritative(receipt: dict[str, Any]) -> bool:
    if "capability_promotion_authoritative" in receipt:
        return _flag(receipt.get("capability_promotion_authoritative"))
    gate = receipt.get("capability_gate")
    if isinstance(gate, dict):
        return _flag(gate.get("promotion_authoritative"))
    return False


def _production_route_requires_capability_gate(receipt: dict[str, Any]) -> bool:
    if "production_route_requires_capability_gate" in receipt:
        return _flag(receipt.get("production_route_requires_capability_gate"))
    gate = receipt.get("capability_gate")
    return isinstance(gate, dict) and bool(gate)


def _production_route_eligible(receipt: dict[str, Any]) -> bool:
    if "production_route_eligible" in receipt:
        return _flag(receipt.get("production_route_eligible"), default=True)
    return True


def _local_frontdoor_requires_worker(receipt: dict[str, Any]) -> bool:
    if _flag(receipt.get("cloud_proxy")):
        return False
    if _lower(receipt.get("usage_bucket")) not in LOCAL_USAGE_BUCKETS:
        return False
    frontdoor = _lower(receipt.get("frontdoor"))
    return "llm.home.arpa" in frontdoor


def audit_route_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    """Audit a route receipt as proof, not just telemetry."""

    receipt = receipt if isinstance(receipt, dict) else {}
    failures: list[str] = []
    warnings: list[str] = []
    missing = [field for field in REQUIRED_ROUTE_RECEIPT_FIELDS if field not in receipt]
    if missing:
        failures.append("missing_required_fields")
    for field in CRITICAL_STRING_FIELDS:
        if field in receipt and not _clean(receipt.get(field)):
            failures.append(f"empty_critical_field:{field}")
    for field in STRICT_BOOL_FIELDS:
        if field in receipt and not isinstance(receipt.get(field), bool):
            failures.append(f"type_mismatch:{field}:bool")
    for field in STRICT_NUMERIC_FIELDS:
        if field in receipt and not _is_number(receipt.get(field)):
            failures.append(f"type_mismatch:{field}:number")
    if "peer_path" in receipt and not isinstance(receipt.get("peer_path"), list):
        failures.append("type_mismatch:peer_path:list")
    if "attempts" in receipt and not isinstance(receipt.get("attempts"), list):
        failures.append("type_mismatch:attempts:list")

    status = _lower(receipt.get("status"))
    output_shape = _lower(receipt.get("output_shape"))
    verifier_result = _normalize_verifier_result(receipt.get("verifier_result"))
    target_model = _clean(receipt.get("target_model") or receipt.get("selected_model"))
    route_selected_model = _clean(
        receipt.get("route_selected_model") or receipt.get("selected_model")
    )
    requested_model = _clean(
        receipt.get("requested_model") or receipt.get("target_model")
    )
    effective_model = _clean(
        receipt.get("effective_runtime_model") or receipt.get("selected_model")
    )
    usage_bucket = _lower(receipt.get("usage_bucket"))
    completion_requested = _flag(receipt.get("completion_requested"))
    require_verifier = completion_requested or _flag(
        receipt.get("require_verifier_for_completion")
    )
    policy_id = _clean(receipt.get("policy_id"))
    policy_hash = _clean(receipt.get("policy_hash"))
    policy_state = _lower(receipt.get("policy_lifecycle_state"))
    policy_integrity_valid = _flag(receipt.get("policy_integrity_valid"))
    policy_default_route_allowed = _flag(receipt.get("policy_default_route_allowed"))
    manual_degraded_authorized = _flag(receipt.get("manual_degraded_authorized"))
    policy_production_eligible = _production_route_eligible(receipt)

    if status and status not in VALID_ROUTE_RECEIPT_STATUSES:
        failures.append(f"invalid_status:{status}")
    if status == "completed":
        active_policy = {}
        try:
            from app.services.norllama.route_policy_artifact import (
                active_route_policy_identity,
            )

            active_policy = active_route_policy_identity()
        except Exception as exc:  # pragma: no cover - defensive for standalone audits
            warnings.append(f"active_policy_identity_unavailable:{_clean(exc)[:80]}")
        if not policy_id:
            failures.append("policy_id_missing")
        if not policy_hash:
            failures.append("policy_hash_missing")
        if not policy_integrity_valid:
            failures.append("policy_integrity_invalid")
        if not manual_degraded_authorized and policy_state not in {
            "valid",
            "expiring_soon",
        }:
            failures.append(f"policy_lifecycle_not_allowed:{policy_state or 'blank'}")
        if not manual_degraded_authorized and not policy_default_route_allowed:
            failures.append("policy_default_route_not_allowed")
        if active_policy:
            if policy_id != _clean(active_policy.get("policy_id")):
                failures.append("policy_id_differs_from_active_authority")
            if policy_hash != _clean(active_policy.get("policy_hash")):
                failures.append("policy_hash_differs_from_active_authority")
        if manual_degraded_authorized:
            if policy_production_eligible:
                failures.append("manual_degraded_marked_production_eligible")
            if _flag(receipt.get("cloud_proxy")):
                failures.append("manual_degraded_used_cloud_proxy")
            authorization = receipt.get("manual_degraded_authorization")
            if not isinstance(authorization, dict) or not authorization:
                failures.append("manual_degraded_missing_authorization")
            else:
                for field in (
                    "authorization_id",
                    "authorized_by",
                    "authorization_reason",
                    "authorization_created_at",
                    "authorization_expires_at",
                ):
                    if not _clean(authorization.get(field)):
                        failures.append(f"manual_degraded_missing_{field}")
                if authorization.get("cloud_allowed"):
                    failures.append("manual_degraded_authorization_allows_cloud")
        elif policy_production_eligible is False and policy_state not in {
            "valid",
            "expiring_soon",
        }:
            failures.append("nonproduction_completion_without_valid_policy")
    if status == "completed" and not target_model:
        failures.append("target_model_missing")
    if status == "completed" and not route_selected_model:
        failures.append("route_selected_model_missing")
    if status == "completed" and not requested_model:
        failures.append("requested_model_missing")
    if status == "completed" and not effective_model:
        failures.append("effective_runtime_model_missing")
    model_override_used = _flag(receipt.get("model_override_used"))
    model_override_reason = _clean(receipt.get("model_override_reason"))
    fallback_used = _flag(receipt.get("fallback_used"))
    fallback_reason = _clean(receipt.get("fallback_reason"))
    model_mismatch_explained = (
        (model_override_used and model_override_reason)
        or (fallback_used and fallback_reason)
        or _clean(receipt.get("gateway_substitution_reason"))
    )
    if model_override_used and not model_override_reason:
        failures.append("model_override_without_reason")
    if route_selected_model and _clean(receipt.get("selected_model")):
        if route_selected_model != _clean(receipt.get("selected_model")):
            failures.append("route_selected_model_differs_from_selected_model")
    if (
        route_selected_model
        and requested_model
        and route_selected_model != requested_model
    ):
        if not model_mismatch_explained:
            failures.append("requested_model_differs_from_route_without_override")
    if requested_model and target_model and requested_model != target_model:
        if not model_mismatch_explained:
            failures.append("target_model_differs_from_requested_without_reason")
    if requested_model and effective_model and requested_model != effective_model:
        if not model_mismatch_explained:
            failures.append("effective_model_differs_from_requested_without_reason")
    elif target_model and effective_model and target_model != effective_model:
        if not model_mismatch_explained:
            failures.append("effective_runtime_model_differs_from_target")

    if output_shape not in VALID_OUTPUT_SHAPES:
        failures.append(f"invalid_output_shape:{output_shape or 'blank'}")
    if _flag(receipt.get("cloud_proxy")) and usage_bucket in LOCAL_USAGE_BUCKETS:
        failures.append("cloud_proxy_counted_as_local")
    if not _flag(receipt.get("cloud_proxy")) and usage_bucket in CLOUD_USAGE_BUCKETS:
        warnings.append("local_route_counted_as_cloud_bucket")
    if usage_bucket == "perplexity_web" and _flag(receipt.get("cloud_proxy")):
        failures.append("perplexity_counted_as_cloud_llm_proxy")

    if status == "completed" and output_shape != "complete":
        failures.append(f"bad_output_shape:{output_shape or 'blank'}")
    if completion_requested and output_shape != "complete":
        failures.append("completion_requested_without_complete_output_shape")
    if require_verifier and verifier_result not in GOOD_VERIFIER_RESULTS:
        failures.append("completion_requested_without_verifier_pass")

    if status == "completed" and _local_frontdoor_requires_worker(receipt):
        selected_worker = _clean(receipt.get("selected_worker"))
        target_worker = _clean(receipt.get("target_worker") or selected_worker)
        observed_worker = _clean(receipt.get("observed_worker"))
        observed_worker_source = _lower(receipt.get("observed_worker_source"))
        peer_path = (
            receipt.get("peer_path")
            if isinstance(receipt.get("peer_path"), list)
            else []
        )
        attempts = (
            receipt.get("attempts") if isinstance(receipt.get("attempts"), list) else []
        )
        if not selected_worker:
            failures.append("selected_worker_missing_for_frontdoor_route")
        if not _clean(receipt.get("observed_worker")):
            failures.append("observed_worker_missing_for_frontdoor_route")
        if observed_worker_source != "gateway_response":
            failures.append("observed_worker_source_not_gateway_response")
        if not peer_path:
            failures.append("peer_path_missing_for_frontdoor_route")
        worker_mismatch = bool(
            target_worker and observed_worker and target_worker != observed_worker
        )
        multi_attempt = len(attempts) > 1
        if worker_mismatch or multi_attempt:
            if not _flag(receipt.get("fallback_used")):
                failures.append(
                    "worker_mismatch_without_fallback_used"
                    if worker_mismatch
                    else "multi_attempt_without_fallback_used"
                )
            if not _clean(receipt.get("fallback_reason")):
                failures.append(
                    "worker_mismatch_without_fallback_reason"
                    if worker_mismatch
                    else "multi_attempt_without_fallback_reason"
                )

    benchmark_source = _benchmark_source(receipt)
    benchmark_gate = _benchmark_gate_name(receipt)
    promotion_authoritative = _promotion_authoritative(receipt)
    capability_gate = _capability_gate_name(receipt)
    capability_promotion_authoritative = _capability_promotion_authoritative(receipt)
    model_for_benchmark = effective_model or target_model
    production_route_eligible = _production_route_eligible(receipt)
    if _is_qwen_production_model(model_for_benchmark) and production_route_eligible:
        if benchmark_gate != "production":
            failures.append("qwen_default_without_production_benchmark_gate")
        if not promotion_authoritative:
            failures.append("qwen_default_without_promotion_authoritative")
        if _production_route_requires_capability_gate(receipt):
            if capability_gate not in {"production", "production_capability_backed"}:
                failures.append("qwen_default_without_production_capability_gate")
            if not capability_promotion_authoritative:
                failures.append(
                    "qwen_default_without_capability_promotion_authoritative"
                )
        if not _flag(receipt.get("benchmark_fresh")):
            failures.append("qwen_default_without_fresh_uplink_benchmark")
        if not _clean(receipt.get("benchmark_packet_id")):
            failures.append("qwen_default_without_benchmark_packet_id")
        if not benchmark_source:
            failures.append("qwen_default_without_benchmark_source")
        elif benchmark_source not in UPLINK_BENCHMARK_SOURCES:
            failures.append("qwen_default_not_backed_by_uplink_benchmark")
        score = _json_float(receipt.get("benchmark_score"))
        coverage = _json_float(receipt.get("coverage_ratio"))
        if score < QWEN_PRODUCTION_MIN_BENCHMARK_SCORE:
            failures.append("qwen_default_benchmark_score_below_threshold")
        if coverage < QWEN_PRODUCTION_MIN_COVERAGE_RATIO:
            failures.append("qwen_default_benchmark_coverage_below_threshold")

    if (
        status == "completed"
        and output_shape == "complete"
        and _is_generative_receipt(receipt)
        and (
            _json_int(receipt.get("total_tokens")) == 0
            or _json_int(receipt.get("output_tokens")) == 0
        )
    ):
        failures.append("zero_token_generative_completion")

    return {
        "schema": ROUTE_RECEIPT_AUDIT_SCHEMA,
        "status": "fail" if failures else "warn" if warnings else "pass",
        "pass": not failures,
        "failures": failures,
        "warnings": warnings,
        "missing_required_fields": missing,
        "receipt_id": _clean(receipt.get("request_id")),
        "job_id": _clean(receipt.get("job_id")),
        "target_model": target_model,
        "effective_runtime_model": effective_model,
        "worker_attribution": {
            "selected_worker": _clean(receipt.get("selected_worker")),
            "target_worker": _clean(receipt.get("target_worker")),
            "gateway_selected_worker": _clean(receipt.get("gateway_selected_worker")),
            "observed_worker": _clean(receipt.get("observed_worker")),
            "source": _clean(receipt.get("observed_worker_source")),
            "peer_path": receipt.get("peer_path")
            if isinstance(receipt.get("peer_path"), list)
            else [],
            "attempts": receipt.get("attempts")
            if isinstance(receipt.get("attempts"), list)
            else [],
        },
        "benchmark": {
            "packet_id": _clean(receipt.get("benchmark_packet_id")),
            "fresh": bool(receipt.get("benchmark_fresh")),
            "source": benchmark_source,
            "gate": benchmark_gate,
            "promotion_authoritative": promotion_authoritative,
            "score": receipt.get("benchmark_score") or 0.0,
            "coverage_ratio": receipt.get("coverage_ratio") or 0.0,
            "transport_gate": receipt.get("transport_gate")
            if isinstance(receipt.get("transport_gate"), dict)
            else {},
            "capability_gate": receipt.get("capability_gate")
            if isinstance(receipt.get("capability_gate"), dict)
            else {},
            "capability_promotion_authoritative": (capability_promotion_authoritative),
            "production_route_requires_capability_gate": (
                _production_route_requires_capability_gate(receipt)
            ),
            "production_route_eligible": bool(production_route_eligible),
        },
        "completion_gate": {
            "requested": completion_requested,
            "require_verifier": require_verifier,
            "output_shape": output_shape,
            "verifier_result": verifier_result,
            "complete_shape": output_shape == "complete",
            "verifier_passed": verifier_result in GOOD_VERIFIER_RESULTS,
        },
    }


def receipt_completion_gate_passes(
    receipt: dict[str, Any] | None,
    *,
    audit: dict[str, Any] | None = None,
    require_verifier: bool = False,
) -> bool:
    receipt = receipt if isinstance(receipt, dict) else {}
    audit = audit if isinstance(audit, dict) else audit_route_receipt(receipt)
    if _lower(receipt.get("status")) != "completed":
        return False
    output_shape = _lower(receipt.get("output_shape"))
    if output_shape != "complete":
        return False
    if not bool(audit.get("pass")):
        return False
    if require_verifier:
        return _normalize_verifier_result(receipt.get("verifier_result")) in (
            GOOD_VERIFIER_RESULTS
        )
    return True
