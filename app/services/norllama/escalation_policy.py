"""Deterministic resident-first cloud escalation policy.

The controller ranks stable roles. A signed registry resolves those roles to
current model IDs, endpoints, and transport behavior, so upgrades do not
require changes to routing logic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from app.core.estate_registry import load_model_registry

ESCALATION_DECISION_SCHEMA = "norman.norllama.escalation-decision.v1"
ESCALATION_CONTROLLER_VERSION = "2026.08.17.model-roles-shadow-v3"
MODEL_ROLE_CONFIG_ENV = "NORMAN_NORLLAMA_MODEL_ROLE_CONFIG"
DEFAULT_MODEL_ROLE_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "norllama" / "model_roles.json"
)

ROLE_ORDER = ("resident", "economy", "authority", "frontier")
ROLE_RANK = {role: index for index, role in enumerate(ROLE_ORDER)}


def load_model_role_config(path: str | Path | None = None) -> dict[str, Any]:
    configured_path = str(
        path or os.getenv(MODEL_ROLE_CONFIG_ENV) or DEFAULT_MODEL_ROLE_CONFIG_PATH
    )
    payload = load_model_registry(configured_path)
    roles = payload["roles"]
    for role in ROLE_ORDER:
        row = roles[role]
        if not str(row.get("tier_label") or "").strip():
            raise ValueError(f"Norllama model-role registry is missing {role} label")
    lane_defaults = payload.get("lane_defaults")
    if not isinstance(lane_defaults, dict) or any(
        str(role) not in ROLE_RANK for role in lane_defaults.values()
    ):
        raise ValueError("Norllama model-role registry has invalid lane defaults")
    return payload


MODEL_ROLE_CONFIG = load_model_role_config()
MODEL_ROLES = {role: dict(MODEL_ROLE_CONFIG["roles"][role]) for role in ROLE_ORDER}
MODEL_BY_ROLE = {role: str(row["model"]) for role, row in MODEL_ROLES.items()}
TIER_LABEL_BY_ROLE = {
    role: str(row["tier_label"]).strip().lower() for role, row in MODEL_ROLES.items()
}
ROLE_BY_TIER_LABEL = {label: role for role, label in TIER_LABEL_BY_ROLE.items()}
LANE_ROLE_DEFAULTS = {
    str(lane): str(role)
    for lane, role in dict(MODEL_ROLE_CONFIG["lane_defaults"]).items()
}
RESIDENT_MODEL = MODEL_BY_ROLE["resident"]

ESCALATION_CONTROLLER_CONTRACT = {
    "schema": "norman.norllama.escalation-controller.v1",
    "version": ESCALATION_CONTROLLER_VERSION,
    "mode": "shadow_only",
    "registry_schema": MODEL_ROLE_CONFIG["schema"],
    "registry_version": MODEL_ROLE_CONFIG["version"],
    "roles": MODEL_ROLES,
    "resident_model": RESIDENT_MODEL,
    "tiers": {TIER_LABEL_BY_ROLE[role]: MODEL_BY_ROLE[role] for role in ROLE_ORDER},
    "lane_role_defaults": dict(LANE_ROLE_DEFAULTS),
    "lane_cloud_defaults": {
        lane: TIER_LABEL_BY_ROLE[role] for lane, role in LANE_ROLE_DEFAULTS.items()
    },
    "rules": {
        "resident": "default for local, reversible, low-risk work",
        "economy": "moderate complexity, ambiguity, or cheap cloud verification",
        "authority": "authority, exactness, sensitive data, or consequential actions",
        "frontier": "rare long-horizon planning or final review after authority evidence",
    },
    "frontier_requires_prior_role": str(
        MODEL_ROLE_CONFIG.get("frontier_requires_prior_role") or "authority"
    ),
    "model_confidence_is_advisory_only": True,
    "execution_authority_changed": False,
}


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value) in {"1", "true", "yes", "on", "required"}


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _at_least(current: str, candidate: str) -> str:
    return candidate if ROLE_RANK[candidate] > ROLE_RANK[current] else current


def _controller_maps(
    controller: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    role_rows = controller.get("roles")
    if not isinstance(role_rows, dict):
        role_rows = MODEL_ROLES
    model_by_role = {
        role: str((role_rows.get(role) or {}).get("model") or "").strip()
        for role in ROLE_ORDER
    }
    label_by_role = {
        role: _clean((role_rows.get(role) or {}).get("tier_label") or role)
        for role in ROLE_ORDER
    }
    role_by_label = {label: role for role, label in label_by_role.items()}
    lane_defaults = controller.get("lane_role_defaults")
    if not isinstance(lane_defaults, dict):
        lane_defaults = LANE_ROLE_DEFAULTS
    return (
        model_by_role,
        label_by_role,
        role_by_label,
        {str(lane): str(role) for lane, role in lane_defaults.items()},
    )


def build_shadow_escalation_decision(
    payload: Mapping[str, Any] | None,
    *,
    policy_id: str = "",
    policy_hash: str = "",
    controller: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed advisory model-role recommendation."""

    active_controller = dict(controller or ESCALATION_CONTROLLER_CONTRACT)
    model_by_role, label_by_role, role_by_label, lane_defaults = _controller_maps(
        active_controller
    )
    request = dict(payload or {})
    lane = _clean(request.get("lane") or request.get("task_kind") or "general")
    risk = _clean(request.get("risk") or "low")
    complexity = _clean(request.get("complexity") or "simple")
    local_runtime_healthy = not (
        request.get("local_runtime_healthy") is False
        or request.get("local_healthy") is False
        or _clean(request.get("local_runtime_status"))
        in {"down", "failed", "unhealthy"}
    )
    resident_confidence = max(
        0.0,
        min(
            1.0,
            _number(
                request.get("resident_confidence", request.get("qwen_confidence")),
                1.0,
            ),
        ),
    )
    failed_attempts = max(0, int(_number(request.get("failed_attempts"), 0)))
    prior_values = [
        *(request.get("prior_roles") or []),
        *(request.get("prior_tiers") or []),
    ]
    prior_roles = {
        role_by_label.get(_clean(value), _clean(value))
        for value in prior_values
        if role_by_label.get(_clean(value), _clean(value)) in ROLE_RANK
    }

    authority_aliases = {
        "mutation": ("mutation", "writes_state", "state_change"),
        "external_side_effect": (
            "external_side_effect",
            "side_effects",
            "external_action",
        ),
        "credential_use": ("credential_use", "uses_credentials"),
        "sensitive_data": ("sensitive_data", "private_data"),
        "financial_action": ("financial_action", "purchase", "payment"),
        "exact_identifiers": ("exact_identifiers", "exactness_required"),
        "final_authority": ("final_authority", "authoritative_decision"),
    }
    authority_flags = {
        name
        for name, aliases in authority_aliases.items()
        if any(_truthy(request.get(alias)) for alias in aliases)
    }
    approval_required = bool(
        authority_flags
        & {
            "mutation",
            "external_side_effect",
            "credential_use",
            "financial_action",
        }
    )
    reasons: list[str] = []
    role = "resident"

    if not local_runtime_healthy:
        role = lane_defaults.get(lane, "economy")
        reasons.append("local_runtime_unhealthy")
    if complexity in {"moderate", "medium"}:
        role = _at_least(role, "economy")
        reasons.append("moderate_complexity")
    if complexity in {"complex", "high"}:
        role = _at_least(role, "authority")
        reasons.append("complex_task")
    if failed_attempts >= 1 or resident_confidence < 0.72:
        role = _at_least(role, "economy")
        reasons.append("resident_evidence_insufficient")
    if failed_attempts >= 2:
        role = _at_least(role, "authority")
        reasons.append("repeated_lower_tier_failure")
    if authority_flags or risk in {"high", "critical"}:
        role = _at_least(role, "authority")
        reasons.append("authority_or_risk_boundary")

    requested = _clean(request.get("requested_role") or request.get("requested_tier"))
    requested_role = role_by_label.get(requested, requested)
    if requested_role in ROLE_RANK:
        role = _at_least(role, requested_role)
        reasons.append("operator_requested_role")

    frontier_candidate = bool(
        _truthy(request.get("frontier_candidate"))
        or _truthy(request.get("sol_candidate"))
        or requested_role == "frontier"
        or (
            complexity in {"frontier", "very_high"}
            or _truthy(request.get("long_horizon_planning"))
            or _truthy(request.get("final_check"))
        )
        and (
            risk == "critical"
            or _truthy(request.get("conflicting_evidence"))
            or _truthy(request.get("authority_failed"))
            or _truthy(request.get("terra_failed"))
        )
    )
    required_prior_role = _clean(
        active_controller.get("frontier_requires_prior_role") or "authority"
    )
    authority_attempted = (
        required_prior_role in prior_roles
        or _truthy(request.get("authority_attempted"))
        or _truthy(request.get("prior_authority_evidence"))
        or _truthy(request.get("terra_attempted"))
        or _truthy(request.get("prior_terra_evidence"))
    )
    if frontier_candidate and authority_attempted:
        role = "frontier"
        reasons.append("frontier_rare_escalation_gate_passed")
    elif role == "frontier":
        role = required_prior_role
        reasons.append("frontier_blocked_without_prior_authority")

    if not reasons:
        reasons.append("resident_default_local")

    frontier_gate = {
        "candidate": frontier_candidate,
        "prior_role_required": required_prior_role,
        "prior_role_observed": authority_attempted,
        "passed": role == "frontier",
    }
    resident_signal = {
        "confidence": resident_confidence,
        "failed_attempts": failed_attempts,
        "advisory_only": True,
    }
    return {
        "schema": ESCALATION_DECISION_SCHEMA,
        "controller_version": str(active_controller.get("version") or ""),
        "registry_version": str(active_controller.get("registry_version") or ""),
        "mode": "shadow_only",
        "status": "proposed",
        "lane": lane,
        "risk": risk,
        "complexity": complexity,
        "resident_model": model_by_role["resident"],
        "proposed_role": role,
        "proposed_tier": label_by_role[role],
        "proposed_model": model_by_role[role],
        "cloud_required": role != "resident",
        "approval_required": approval_required,
        "authority_flags": sorted(authority_flags),
        "reason_codes": reasons,
        "frontier_gate": frontier_gate,
        "sol_gate": {
            "candidate": frontier_gate["candidate"],
            "prior_terra_required": True,
            "prior_terra_observed": frontier_gate["prior_role_observed"],
            "passed": frontier_gate["passed"],
        },
        "resident_signal": resident_signal,
        "qwen_signal": resident_signal,
        "policy_id": policy_id,
        "policy_hash": policy_hash,
        "execution_model_unchanged": True,
        "execution_authority_changed": False,
    }
