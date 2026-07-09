from __future__ import annotations

from typing import Any

ROUTE_RECEIPT_AUDIT_SCHEMA = "norman.norllama.route-receipt-audit.v1"

REQUIRED_ROUTE_RECEIPT_FIELDS = (
    "request_id",
    "job_id",
    "phase",
    "task_kind",
    "selected_provider",
    "selected_model",
    "target_model",
    "effective_runtime_model",
    "selected_worker",
    "observed_worker",
    "frontdoor",
    "peer_path",
    "route_reason",
    "policy_mode",
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
NON_EMPTY_ROUTE_RECEIPT_FIELDS = (
    "request_id",
    "job_id",
    "phase",
    "task_kind",
    "selected_provider",
    "selected_model",
    "target_model",
    "effective_runtime_model",
    "selected_worker",
    "frontdoor",
    "peer_path",
    "route_reason",
    "policy_mode",
    "benchmark_packet_id",
    "benchmark_source",
    "usage_bucket",
    "verifier_result",
    "output_shape",
)

BAD_COMPLETION_SHAPES = {"empty", "progress_only", "timeout", "error"}
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
QWEN_PRODUCTION_PREFIXES = ("qwen3.6", "qwen3.5", "nvidia/qwen3.6")
UPLINK_BENCHMARK_SOURCES = {
    "uplink_benchmark",
    "uplink_lane_benchmark",
    "uplink_route_proof",
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


def _critical_value_present(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return any(_critical_value_present(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    return bool(_clean(value))


def _is_qwen_production_model(model: str) -> bool:
    clean = _lower(model).replace("_", "-")
    return clean.startswith(QWEN_PRODUCTION_PREFIXES)


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


def _local_frontdoor_requires_worker(receipt: dict[str, Any]) -> bool:
    if _flag(receipt.get("cloud_proxy")):
        return False
    if _lower(receipt.get("usage_bucket")) not in LOCAL_USAGE_BUCKETS:
        return False
    frontdoor = _lower(receipt.get("frontdoor"))
    if "llm.home.arpa" not in frontdoor:
        return False
    scope = _lower(receipt.get("routing_scope"))
    source = _lower(receipt.get("route_attribution_source"))
    return scope in {"frontdoor", "frontdoor_worker"} or source in {
        "frontdoor_delegated",
        "gateway_response",
    }


def audit_route_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    """Audit a route receipt as proof, not just telemetry."""

    receipt = receipt if isinstance(receipt, dict) else {}
    failures: list[str] = []
    warnings: list[str] = []
    missing = [field for field in REQUIRED_ROUTE_RECEIPT_FIELDS if field not in receipt]
    if missing:
        failures.append("missing_required_fields")

    status = _lower(receipt.get("status"))
    output_shape = _lower(receipt.get("output_shape"))
    verifier_result = _lower(receipt.get("verifier_result"))
    target_model = _clean(receipt.get("target_model") or receipt.get("selected_model"))
    effective_model = _clean(
        receipt.get("effective_runtime_model") or receipt.get("selected_model")
    )
    usage_bucket = _lower(receipt.get("usage_bucket"))
    completion_requested = _flag(receipt.get("completion_requested"))
    require_verifier = completion_requested or _flag(
        receipt.get("require_verifier_for_completion")
    )
    route_proof_required = _flag(receipt.get("route_proof_required"))
    critical_required = status in {"accepted", "completed"} or (
        completion_requested or route_proof_required
    )
    empty_critical = [
        field
        for field in NON_EMPTY_ROUTE_RECEIPT_FIELDS
        if field in receipt and not _critical_value_present(receipt.get(field))
    ]
    absent_critical = [
        field for field in NON_EMPTY_ROUTE_RECEIPT_FIELDS if field not in receipt
    ]
    if critical_required and (empty_critical or absent_critical):
        failures.append("critical_fields_empty")

    if status == "completed" and not target_model:
        failures.append("target_model_missing")
    if status == "completed" and not effective_model:
        failures.append("effective_runtime_model_missing")
    if target_model and effective_model and target_model != effective_model:
        warnings.append("effective_runtime_model_differs_from_target")

    if _flag(receipt.get("cloud_proxy")) and usage_bucket in LOCAL_USAGE_BUCKETS:
        failures.append("cloud_proxy_counted_as_local")
    if not _flag(receipt.get("cloud_proxy")) and usage_bucket in CLOUD_USAGE_BUCKETS:
        warnings.append("local_route_counted_as_cloud_bucket")
    if usage_bucket == "perplexity_web" and _flag(receipt.get("cloud_proxy")):
        failures.append("perplexity_counted_as_cloud_llm_proxy")

    if status == "completed" and output_shape in BAD_COMPLETION_SHAPES:
        failures.append(f"bad_output_shape:{output_shape}")
    if completion_requested and output_shape in BAD_COMPLETION_SHAPES:
        failures.append("completion_requested_without_complete_output_shape")
    if require_verifier and verifier_result not in GOOD_VERIFIER_RESULTS:
        failures.append("completion_requested_without_verifier_pass")

    if status == "completed" and _local_frontdoor_requires_worker(receipt):
        if not _clean(receipt.get("observed_worker")):
            failures.append("observed_worker_missing_for_frontdoor_route")
    if _flag(receipt.get("fallback_used")) and not _clean(
        receipt.get("fallback_reason")
    ):
        failures.append("fallback_used_without_reason")

    benchmark_source = _benchmark_source(receipt)
    model_for_benchmark = effective_model or target_model
    if _is_qwen_production_model(model_for_benchmark):
        if not _flag(receipt.get("benchmark_fresh")):
            failures.append("qwen_default_without_fresh_uplink_benchmark")
        if not _clean(receipt.get("benchmark_packet_id")):
            failures.append("qwen_default_without_benchmark_packet_id")
        if benchmark_source and benchmark_source not in UPLINK_BENCHMARK_SOURCES:
            failures.append("qwen_default_not_backed_by_uplink_benchmark")

    if status == "completed" and _json_int(receipt.get("total_tokens")) == 0:
        warnings.append("completed_receipt_has_zero_token_accounting")

    return {
        "schema": ROUTE_RECEIPT_AUDIT_SCHEMA,
        "status": "fail" if failures else "warn" if warnings else "pass",
        "pass": not failures,
        "failures": failures,
        "warnings": warnings,
        "missing_required_fields": missing,
        "empty_critical_fields": empty_critical,
        "absent_critical_fields": absent_critical if critical_required else [],
        "receipt_id": _clean(receipt.get("request_id")),
        "job_id": _clean(receipt.get("job_id")),
        "target_model": target_model,
        "effective_runtime_model": effective_model,
        "worker_attribution": {
            "selected_worker": _clean(receipt.get("selected_worker")),
            "observed_worker": _clean(receipt.get("observed_worker")),
            "source": _clean(receipt.get("observed_worker_source")),
            "peer_path": receipt.get("peer_path")
            if isinstance(receipt.get("peer_path"), list)
            else [],
        },
        "benchmark": {
            "packet_id": _clean(receipt.get("benchmark_packet_id")),
            "fresh": bool(receipt.get("benchmark_fresh")),
            "source": benchmark_source,
            "score": receipt.get("benchmark_score") or 0.0,
            "coverage_ratio": receipt.get("coverage_ratio") or 0.0,
        },
        "completion_gate": {
            "requested": completion_requested,
            "require_verifier": require_verifier,
            "output_shape": output_shape,
            "verifier_result": verifier_result,
            "complete_shape": output_shape not in BAD_COMPLETION_SHAPES,
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
    output_shape = _lower(receipt.get("output_shape"))
    if output_shape in BAD_COMPLETION_SHAPES:
        return False
    if not bool(audit.get("pass")):
        return False
    if require_verifier:
        return _lower(receipt.get("verifier_result")) in GOOD_VERIFIER_RESULTS
    return True
