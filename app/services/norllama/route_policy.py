from __future__ import annotations

import hashlib
import json
from typing import Any

ROUTE_POLICY_SCHEMA = "norman.norllama.route-policy.v1"
ROUTE_POLICY_VERSION = "2026.07.10.route-proof"
ROUTE_POLICY_COMPILED_AT = "2026-07-10T00:00:00Z"
ROUTE_POLICY_EXPIRES_AT = "2026-07-17T00:00:00Z"

BENCHMARK_GATE_THRESHOLDS = {
    "smoke": 1,
    "staging": 3,
    "production": 5,
}
CAPABILITY_GATE_ORDER = {
    "": 0,
    "unproven": 0,
    "cases_defined_unproven": 0,
    "failed": 0,
    "executed_failed": 0,
    "smoke": 1,
    "canary": 1,
    "canary_live": 1,
    "smoke_backed": 1,
    "staging": 2,
    "staging_capability_backed": 2,
    "production": 3,
    "production_capability_backed": 3,
}
PRODUCTION_GATE_MIN_COLD_SAMPLES = 1
PRODUCTION_GATE_MIN_WARM_SAMPLES = 1

QWEN35_HEAVY_JUDGE_MODEL_NEEDLES = (
    "qwen3.5:122b",
    "qwen3.5-122b",
    "qwen3.5/122b",
    "nvidia/qwen3.5-122b",
)
QWEN35_HEAVY_JUDGE_ALLOWED_LANES = frozenset({"judge", "verifier"})

ROUTE_POLICY_MODELS = {
    "general_reasoning_floor": "qwen3.6/qwen3.5-class",
    "router": "qwen3.6:35b-a3b-q4_K_M",
    "coding_operator": "qwen3.6:27b",
    "local_heavyweight_judge": "qwen3.5:122b-a10b-q4_K_M",
    "fallback_small": "gemma4-or-qwen-tiny-class",
}

ROUTE_POLICY_LANES = {
    "planner": {"class": "qwen3.6", "gate": "production"},
    "coder": {"class": "qwen3.6", "gate": "production"},
    "summarizer": {"class": "qwen3.6", "gate": "production"},
    "filter": {"class": "qwen3.6", "gate": "production"},
    "verifier": {"class": "qwen3.5-or-qwen3.6", "gate": "production"},
    "judge": {"class": "qwen3.5-heavy", "gate": "production"},
    "specialist": {"class": "lane-specific", "gate": "smoke-or-better"},
    "lab": {"class": "explicit-request-only", "gate": "lab"},
}

ROUTE_POLICY_PLACEMENT = {
    "frontdoor": "https://llm.home.arpa",
    "router_node": "mac-mini-133",
    "primary_brain_worker": "spark-151",
    "specialist_worker": "spark-150",
    "fallback_node": "mac-mini-133",
    "qwen35_122b_allowed_lanes": sorted(QWEN35_HEAVY_JUDGE_ALLOWED_LANES),
    "fallback_node_heavy_models_allowed": False,
}

ROUTE_POLICY_RESIDENCY = {
    "resident": ["qwen3.6-router", "qwen3.6-code", "rerank", "safety"],
    "warm_on_demand": ["qwen3.5-122b-judge", "ocr", "asr", "doc-parse"],
    "lab": ["world", "graph", "packet", "forecasting", "gui-grounding"],
}

ROUTE_POLICY_FALLBACKS = {
    "worker_mismatch_requires_receipt_fallback": True,
    "allow_cloud_fallback": False,
    "allow_local_degraded_fallback": True,
    "fallback_reason_required": True,
}

ROUTE_POLICY_CLOUD_POLICY = {
    "cloud_llm_default": "disabled",
    "cloud_escalation": "explicit_policy_or_user_authorized_only",
    "cloud_proxy_counts_as_cloud": True,
    "perplexity_web_is_search_not_cloud_llm": True,
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def is_qwen35_heavy_judge_model(model: Any) -> bool:
    clean = _clean(model).lower().replace("_", "-")
    return any(needle in clean for needle in QWEN35_HEAVY_JUDGE_MODEL_NEEDLES)


def restrict_lanes_for_model(model: Any, lanes: set[str]) -> set[str]:
    if is_qwen35_heavy_judge_model(model):
        return set(lanes) & set(QWEN35_HEAVY_JUDGE_ALLOWED_LANES)
    return lanes


def benchmark_gate_for_counts(
    *,
    accepted_count: Any,
    total_count: Any = None,
    cold_sample_count: Any = None,
    warm_sample_count: Any = None,
) -> dict[str, Any]:
    accepted = _int(accepted_count)
    total = _int(total_count)
    cold = _int(cold_sample_count)
    warm = _int(warm_sample_count)
    if accepted <= 0:
        gate = "historical" if total == 0 else "failed"
    elif (
        accepted >= BENCHMARK_GATE_THRESHOLDS["production"]
        and cold >= PRODUCTION_GATE_MIN_COLD_SAMPLES
        and warm >= PRODUCTION_GATE_MIN_WARM_SAMPLES
    ):
        gate = "production"
    elif accepted >= BENCHMARK_GATE_THRESHOLDS["staging"]:
        gate = "staging"
    else:
        gate = "smoke"
    return {
        "schema": f"{ROUTE_POLICY_SCHEMA}.benchmark-gate",
        "policy_version": ROUTE_POLICY_VERSION,
        "gate": gate,
        "accepted_count": accepted,
        "total_count": total,
        "cold_sample_count": cold,
        "warm_sample_count": warm,
        "thresholds": dict(BENCHMARK_GATE_THRESHOLDS),
        "production_requires_cold_and_warm": True,
        "promotion_authoritative": gate == "production",
        "route_eligible": gate in {"smoke", "staging", "production"},
    }


def gate_rank(value: Any, *, capability: bool = False) -> int:
    clean = _clean(value).lower()
    if not clean:
        return 0
    if capability:
        return CAPABILITY_GATE_ORDER.get(clean, 0)
    if clean in BENCHMARK_GATE_THRESHOLDS:
        return BENCHMARK_GATE_THRESHOLDS[clean]
    if clean == "historical":
        return 0
    return 0


def capability_gate_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("gate") or value.get("name")
    clean = _clean(value).lower()
    return clean or "unproven"


def capability_gate_promotion_authoritative(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(value.get("promotion_authoritative"))


def capability_gate_required(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    clean = _clean(value).lower()
    if not clean:
        return False
    return clean in {"1", "true", "yes", "on", "required"}


def capability_gate_allows_production_default(
    *,
    capability_gate: dict[str, Any] | None,
    production_route_requires_capability_gate: Any = False,
) -> bool:
    """Return whether capability evidence is strong enough for default routing."""

    if not capability_gate_required(production_route_requires_capability_gate):
        return True
    gate = capability_gate_name(capability_gate or {})
    return bool(
        gate_rank(gate, capability=True) >= gate_rank("production", capability=True)
        and capability_gate_promotion_authoritative(capability_gate or {})
    )


def capability_route_state(
    *,
    capability_gate: dict[str, Any] | None,
    production_route_requires_capability_gate: Any = False,
) -> str:
    if not capability_gate_required(production_route_requires_capability_gate):
        return "not_required"
    gate = capability_gate_name(capability_gate or {})
    rank = gate_rank(gate, capability=True)
    if rank >= gate_rank("production", capability=True):
        return (
            "production_capability_backed"
            if capability_gate_promotion_authoritative(capability_gate or {})
            else "production_capability_not_authoritative"
        )
    if rank >= gate_rank("staging", capability=True):
        return "staging_capability_only"
    if rank >= gate_rank("smoke", capability=True):
        return "canary_capability_only"
    return "capability_unproven"


def _route_policy_contract_base() -> dict[str, Any]:
    return {
        "schema": ROUTE_POLICY_SCHEMA,
        "version": ROUTE_POLICY_VERSION,
        "compiled_at": ROUTE_POLICY_COMPILED_AT,
        "expires_at": ROUTE_POLICY_EXPIRES_AT,
        "local_first": True,
        "allow_cloud_proxy": False,
        "allow_cloud_tool_proxy": False,
        "escalation_policy": "explicit_cloud_only",
        "cost_posture": "local_token_first",
        "planner": "norllama",
        "model_proxy": "norllama",
        "model_selection": "warm_policy",
        "models": dict(ROUTE_POLICY_MODELS),
        "lanes": {lane: dict(policy) for lane, policy in ROUTE_POLICY_LANES.items()},
        "benchmark_gates": {
            "thresholds": dict(BENCHMARK_GATE_THRESHOLDS),
            "production_requires_distinct_cold_warm_samples": True,
            "qwen_production_requires_gate": "production",
            "qwen_production_requires_promotion_authoritative": True,
            "production_route_requires_capability_gate": True,
        },
        "capability_gates": {
            "order": dict(CAPABILITY_GATE_ORDER),
            "production_requires_gate": "production",
            "production_requires_promotion_authoritative": True,
            "staging_allows_internal_canary": True,
            "unproven_allows_manual_or_lab_only": True,
        },
        "placement": dict(ROUTE_POLICY_PLACEMENT),
        "residency": {
            key: list(value) for key, value in ROUTE_POLICY_RESIDENCY.items()
        },
        "fallbacks": dict(ROUTE_POLICY_FALLBACKS),
        "cloud_policy": dict(ROUTE_POLICY_CLOUD_POLICY),
        "emergency_overlays": {
            "allowed": True,
            "requires_expiration": True,
            "max_ttl_seconds": 6 * 60 * 60,
        },
    }


def route_policy_hash(policy: dict[str, Any] | None = None) -> str:
    """Return the stable content hash for a route-policy artifact."""

    payload = dict(policy or _route_policy_contract_base())
    payload.pop("policy_id", None)
    payload.pop("policy_hash", None)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def route_policy_contract() -> dict[str, Any]:
    contract = _route_policy_contract_base()
    digest = route_policy_hash(contract)
    contract["policy_hash"] = digest
    contract["policy_id"] = f"{ROUTE_POLICY_VERSION}:{digest[:12]}"
    return contract
