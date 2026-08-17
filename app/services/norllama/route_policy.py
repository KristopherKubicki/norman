from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from app.core.estate_registry import (
    load_fleet_topology,
    model_capability,
    model_for_role,
)
from app.services.norllama.escalation_policy import (
    ESCALATION_CONTROLLER_CONTRACT,
    MODEL_ROLES,
    RESIDENT_MODEL,
)

ROUTE_POLICY_SCHEMA = "norman.norllama.route-policy.v1"
ROUTE_POLICY_VERSION = "2026.08.16.registry-driven-v3"
ROUTE_POLICY_EXPIRY_WARN_SECONDS = 72 * 60 * 60
ROUTE_POLICY_EXPIRED_STATE = "expired_blocked"

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

ROUTE_POLICY_MODELS = {
    "general_reasoning_floor": "resident-role",
    "router": RESIDENT_MODEL,
    "coding_operator": RESIDENT_MODEL,
    "judge": model_for_role("authority"),
    "fallback": model_for_role("economy"),
}

ROUTE_POLICY_LANES = {
    "planner": {"class": "resident", "gate": "production"},
    "coder": {"class": "resident", "gate": "production"},
    "summarizer": {"class": "resident", "gate": "production"},
    "filter": {"class": "resident", "gate": "production"},
    "verifier": {"class": "resident", "gate": "production"},
    "judge": {"class": "authority", "gate": "production"},
    "specialist": {"class": "lane-specific", "gate": "smoke-or-better"},
    "lab": {"class": "explicit-request-only", "gate": "lab"},
}

_TOPOLOGY = load_fleet_topology()
_RESIDENT_POOL = dict(_TOPOLOGY.get("resident_pool") or {})
_RESIDENT_WORKERS = list(_RESIDENT_POOL.get("runtime_workers") or [])
_PRODUCTION_WORKERS = [
    worker_id
    for worker_id, row in dict(_TOPOLOGY.get("workers") or {}).items()
    if isinstance(row, dict) and row.get("role") == "production"
]
_FALLBACK_WORKERS = [
    worker_id
    for worker_id, row in dict(_TOPOLOGY.get("workers") or {}).items()
    if isinstance(row, dict) and row.get("role") == "fallback"
]

ROUTE_POLICY_PLACEMENT = {
    "frontdoor": str(dict(_TOPOLOGY.get("frontdoors") or {}).get("llm") or ""),
    "primary_brain_worker": (
        _RESIDENT_WORKERS[0] if _RESIDENT_WORKERS else _PRODUCTION_WORKERS[0]
    ),
    "specialist_worker": (
        _PRODUCTION_WORKERS[-1] if _PRODUCTION_WORKERS else _RESIDENT_WORKERS[0]
    ),
    "fallback_node": _FALLBACK_WORKERS[0] if _FALLBACK_WORKERS else "",
    "resident_ollama_bases": list(MODEL_ROLES["resident"].get("endpoints") or []),
    "resident_runtime_workers": list(_RESIDENT_WORKERS),
    "fallback_node_heavy_models_allowed": False,
}

ROUTE_POLICY_RESIDENCY = {
    "resident": [RESIDENT_MODEL, "rerank", "safety"],
    "warm_on_demand": ["ocr", "doc-parse"],
    "manual_only": [],
    "lab": ["world", "graph", "packet", "forecasting", "gui-grounding"],
}

CLOUD_FALLBACK_BEDROCK_MODEL = "openai.gpt-5.6-terra"

ROUTE_POLICY_FALLBACKS = {
    "worker_mismatch_requires_receipt_fallback": True,
    "allow_cloud_fallback": True,
    "cloud_fallback_aliases": ["norman-code", "norman-code-governed"],
    "cloud_fallback_provider": "aws-bedrock",
    "cloud_fallback_model": CLOUD_FALLBACK_BEDROCK_MODEL,
    "cloud_fallback_lane": "coder",
    "allow_local_degraded_fallback": True,
    "fallback_reason_required": True,
}


def _explicit_cloud_models() -> dict[str, dict[str, str]]:
    selections: dict[str, dict[str, str]] = {}
    for role in ("economy", "authority", "frontier"):
        row = MODEL_ROLES[role]
        model = str(row["model"])
        provider = str(row.get("provider") or "aws-bedrock")
        for alias in row.get("aliases") or [model]:
            selections[str(alias)] = {
                "provider": provider,
                "model": model,
                "lane": "coder",
                "role": role,
            }
    return selections


ROUTE_POLICY_CLOUD_POLICY = {
    "cloud_llm_default": "disabled",
    "cloud_escalation": "explicit_policy_or_user_authorized_only",
    "cloud_proxy_counts_as_cloud": True,
    "perplexity_web_is_search_not_cloud_llm": True,
    "explicit_cloud_models": _explicit_cloud_models(),
}

ROUTE_POLICY_LIFECYCLE_POLICY = {
    "expiry_enforced": True,
    "warn_before_seconds": ROUTE_POLICY_EXPIRY_WARN_SECONDS,
    "expired_state": ROUTE_POLICY_EXPIRED_STATE,
    "expired_default_route_allowed": False,
    "expired_manual_degraded_allowed": True,
    "refresh_required": True,
    "refresh_source": "compiled_route_policy_artifact",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def cloud_fallback_allowed_for_alias(
    requested_model: Any,
    *,
    fallback_policy: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether the signed fallback policy covers this public alias."""

    policy = dict(fallback_policy or ROUTE_POLICY_FALLBACKS)
    aliases = policy.get("cloud_fallback_aliases")
    if not isinstance(aliases, list):
        return False
    requested = _clean(requested_model).lower()
    return bool(policy.get("allow_cloud_fallback")) and requested in {
        _clean(alias).lower() for alias in aliases if _clean(alias)
    }


def explicit_cloud_selection_for_model(
    requested_model: Any,
    *,
    cloud_policy: Mapping[str, Any] | None = None,
) -> dict[str, str] | None:
    """Resolve an exact, policy-approved public cloud model alias."""

    requested = _clean(requested_model).lower()
    policy = (
        dict(ROUTE_POLICY_CLOUD_POLICY) if cloud_policy is None else dict(cloud_policy)
    )
    selections = policy.get("explicit_cloud_models")
    if not requested or not isinstance(selections, Mapping):
        return None
    selected = selections.get(requested)
    if not isinstance(selected, Mapping):
        return None
    provider = _clean(selected.get("provider")).lower().replace("_", "-")
    model = _clean(selected.get("model"))
    lane = _clean(selected.get("lane")).lower()
    if provider != "aws-bedrock" or not model or not lane:
        return None
    return {
        "provider": provider,
        "model": model,
        "lane": lane,
    }


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def is_qwen35_heavy_judge_model(model: Any) -> bool:
    return bool(model_capability(_clean(model), "manual_only", False))


def restrict_lanes_for_model(model: Any, lanes: set[str]) -> set[str]:
    allowed = model_capability(_clean(model), "allowed_lanes", None)
    if isinstance(allowed, list):
        return set(lanes) & {str(lane) for lane in allowed}
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


def parse_route_policy_timestamp(value: Any) -> datetime | None:
    clean = _clean(value)
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def route_policy_lifecycle(
    policy: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return runtime lifecycle state for a compiled route-policy artifact."""

    from app.services.norllama.route_policy_artifact import (
        validate_route_policy_artifact,
    )

    artifact = dict(policy or route_policy_contract())
    validation = validate_route_policy_artifact(artifact, now=now)
    state = _clean(validation.get("state")) or "refresh_failed"
    severity = (
        "ok"
        if state == "valid"
        else "warning"
        if state == "expiring_soon"
        else "critical"
    )
    default_route_allowed = bool(validation.get("default_route_allowed"))
    seconds_to_expiry = validation.get("seconds_to_expiry")
    degraded = not default_route_allowed
    reason = _clean(validation.get("reason")) or state
    warn_before_seconds = ROUTE_POLICY_EXPIRY_WARN_SECONDS
    lifecycle_policy = (
        artifact.get("lifecycle_policy")
        if isinstance(artifact.get("lifecycle_policy"), dict)
        else ROUTE_POLICY_LIFECYCLE_POLICY
    )

    return {
        "schema": f"{ROUTE_POLICY_SCHEMA}.lifecycle",
        "policy_version": _clean(artifact.get("version")) or ROUTE_POLICY_VERSION,
        "policy_id": _clean(validation.get("policy_id") or artifact.get("policy_id")),
        "policy_hash": _clean(
            validation.get("policy_hash") or artifact.get("policy_hash")
        ),
        "compiled_at": _clean(artifact.get("compiled_at") or artifact.get("issued_at")),
        "issued_at": _clean(artifact.get("issued_at")),
        "not_before": _clean(artifact.get("not_before")),
        "expires_at": _clean(artifact.get("expires_at")),
        "state": state,
        "severity": severity,
        "reason": reason,
        "seconds_to_expiry": seconds_to_expiry,
        "warn_before_seconds": warn_before_seconds,
        "integrity_valid": bool(validation.get("integrity_valid")),
        "expiry_enforced": bool(lifecycle_policy.get("expiry_enforced", True)),
        "default_route_allowed": default_route_allowed,
        "manual_degraded_allowed": bool(
            lifecycle_policy.get("expired_manual_degraded_allowed", True)
        ),
        "refresh_required": bool(lifecycle_policy.get("refresh_required", True)),
        "degraded": degraded,
        "validation": validation,
    }


def _route_policy_contract_base() -> dict[str, Any]:
    return {
        "schema": ROUTE_POLICY_SCHEMA,
        "version": ROUTE_POLICY_VERSION,
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
            "capability_gate_exemptions": {
                "low_risk_local_text_non_mutating": {
                    "applies_to_lanes": [
                        "chat",
                        "planner",
                        "summarizer",
                        "verifier",
                    ],
                    "allowed_task_risk": ["low"],
                    "mutation_allowed": False,
                    "external_side_effects_allowed": False,
                    "cloud_allowed": False,
                    "requires_transport_gate": "production",
                    "reason": (
                        "Low-risk local text work may use transport-backed Qwen "
                        "routes while representative capability suites remain "
                        "canary-only; mutating or high-authority work still "
                        "requires explicit capability proof."
                    ),
                }
            },
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
        "escalation_controller": copy.deepcopy(ESCALATION_CONTROLLER_CONTRACT),
        "lifecycle_policy": dict(ROUTE_POLICY_LIFECYCLE_POLICY),
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
    from app.services.norllama.route_policy_artifact import load_route_policy_artifact

    loaded = load_route_policy_artifact()
    artifact = (
        loaded.get("artifact") if isinstance(loaded.get("artifact"), dict) else {}
    )
    return dict(artifact or {})
