"""Shared, fail-closed work-routing classification contract.

This classification describes why a turn may use deterministic state, a local
model, a frontier model, or must wait for an operator. It supplements existing
route proofs and approval gates; it does not authorize an execution by itself.
"""

from __future__ import annotations

from typing import Any, Mapping

try:
    from app.services.console_runtime.policy import CLOUD_LLM_PROVIDERS
except Exception:  # pragma: no cover - keep this usable by lightweight callers.
    CLOUD_LLM_PROVIDERS = {
        "anthropic",
        "aws-bedrock",
        "aws_bedrock",
        "bedrock",
        "codex",
        "openai",
        "openai-compatible",
        "openai_compatible",
        "openai-direct",
        "openai_direct",
    }


WORK_CLASSIFICATION_SCHEMA = "norman.work-classification.v1"

_WORK_CLASS_PROPERTIES = {
    "deterministic": {
        "execution_authority": "none",
        "review_required": False,
        "human_approval_required": False,
        "evidence_required": "deterministic_receipt",
    },
    "local": {
        "execution_authority": "local",
        "review_required": False,
        "human_approval_required": False,
        "evidence_required": "none",
    },
    "local_review": {
        "execution_authority": "local",
        "review_required": True,
        "human_approval_required": False,
        "evidence_required": "verification_receipt",
    },
    "frontier": {
        "execution_authority": "frontier",
        "review_required": True,
        "human_approval_required": False,
        "evidence_required": "frontier_review",
    },
    "approval_required": {
        "execution_authority": "none",
        "review_required": True,
        "human_approval_required": True,
        "evidence_required": "approval_receipt",
    },
}

_VALID_REASON_CODES = {
    "trusted_deterministic_status",
    "trusted_deterministic_command",
    "trusted_approval_requirement",
    "external_mutation",
    "destructive_risk",
    "high_risk",
    "forced_frontier_route",
    "locked_frontier_route",
    "effective_frontier_runtime",
    "local_review_code",
    "local_review_kpi",
    "local_review_plan",
    "local_review_scout",
    "local_review_verify",
    "local_safe_analysis",
}

_REASON_LABELS = {
    "trusted_deterministic_status": "trusted status handler",
    "trusted_deterministic_command": "trusted read-only command handler",
    "trusted_approval_requirement": "approval gate",
    "external_mutation": "external mutation risk",
    "destructive_risk": "destructive risk",
    "high_risk": "high-risk work",
    "forced_frontier_route": "explicit frontier route",
    "locked_frontier_route": "locked frontier route",
    "effective_frontier_runtime": "effective frontier runtime",
    "local_review_code": "local code review",
    "local_review_kpi": "local KPI review",
    "local_review_plan": "local planning review",
    "local_review_scout": "local scout review",
    "local_review_verify": "local verification review",
    "local_safe_analysis": "local analysis",
}

_REQUIRED_REASON_CODES = {
    "deterministic": {
        "trusted_deterministic_status",
        "trusted_deterministic_command",
    },
    "approval_required": {
        "trusted_approval_requirement",
        "external_mutation",
        "destructive_risk",
        "high_risk",
    },
    "frontier": {
        "forced_frontier_route",
        "locked_frontier_route",
        "effective_frontier_runtime",
    },
    "local_review": {
        "local_review_code",
        "local_review_kpi",
        "local_review_plan",
        "local_review_scout",
        "local_review_verify",
    },
    "local": {"local_safe_analysis"},
}

_LOCAL_REVIEW_TASK_KINDS = {"code", "judge", "kpi", "plan", "scout", "verify"}
_FRONTIER_RUNTIME_ALIASES = {
    "anthropic",
    "aws-bedrock",
    "aws_bedrock",
    "bedrock",
    "claude",
    "codex",
    "kimi",
    "openai",
    "openai-compatible",
    "openai_compatible",
    "openai-direct",
    "openai_direct",
    # The TUI's qwen runtime is Bedrock-backed. Local Qwen is represented by
    # the Norllama/localllm runtime, not this surface name.
    "qwen",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower().replace("_", "-")


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool:
    return value is True


def _frontier_runtime(*values: Any) -> bool:
    for value in values:
        runtime = _lower(value)
        if runtime in _FRONTIER_RUNTIME_ALIASES:
            return True
        if runtime in {
            str(provider).lower().replace("_", "-") for provider in CLOUD_LLM_PROVIDERS
        }:
            return True
    return False


def _operator_summary(work_class: str, reason_codes: list[str]) -> str:
    labels = ", ".join(_REASON_LABELS[reason] for reason in reason_codes)
    return f"{work_class.replace('_', ' ')}: {labels}."


def work_classification_summary(value: Any) -> str:
    """Return the trusted operator-facing summary, or an empty string."""

    sanitized = sanitize_work_classification(value)
    return _clean(sanitized.get("operator_summary"))


def _contract(work_class: str, reason_codes: list[str]) -> dict[str, Any]:
    return {
        "schema": WORK_CLASSIFICATION_SCHEMA,
        "work_class": work_class,
        **_WORK_CLASS_PROPERTIES[work_class],
        "reason_codes": reason_codes,
        "operator_summary": _operator_summary(work_class, reason_codes),
    }


def classify_work(
    *,
    prompt_classification: Mapping[str, Any] | None = None,
    deterministic_kind: str = "",
    attachment_count: int = 0,
    active_work: bool = False,
    route_locked: bool = False,
    force_requested_runtime: bool = False,
    requested_runtime: str = "",
    effective_runtime: str = "",
    selected_provider: str = "",
    external_mutation: bool = False,
    destructive: bool = False,
    approval_required: bool = False,
    risk_level: str = "",
    task_kind: str = "",
) -> dict[str, Any]:
    """Classify trusted routing facts into the shared work contract.

    ``deterministic_kind`` is intentionally an explicit handler signal. Prompt
    wording such as "status" or "run a command" never makes a turn
    deterministic on its own.
    """

    classification = _as_mapping(prompt_classification)
    normalized_kind = _lower(deterministic_kind)
    normalized_task_kind = _lower(task_kind or classification.get("task_kind"))
    normalized_risk = _lower(risk_level or classification.get("risk_level"))
    requires_approval = (
        _bool(approval_required)
        or _bool(classification.get("requires_approval"))
        or _bool(classification.get("external_side_effects_possible"))
    )
    external_risk = (
        _bool(external_mutation)
        or _bool(classification.get("external_side_effects_possible"))
        or _lower(classification.get("risk_class"))
        in {"destructive", "external-mutation", "external_mutation"}
    )
    destructive_risk = (
        _bool(destructive)
        or _lower(classification.get("risk_class")) == "destructive"
        or normalized_risk == "critical"
    )
    high_risk = normalized_risk in {"high", "critical"}
    requested_frontier = _frontier_runtime(requested_runtime)
    effective_frontier = _frontier_runtime(effective_runtime, selected_provider)
    route_is_frontier = effective_frontier or (
        requested_frontier and (_bool(force_requested_runtime) or _bool(route_locked))
    )

    deterministic_allowed = (
        normalized_kind in {"status", "command"}
        and max(0, int(attachment_count or 0)) == 0
        and not _bool(active_work)
        and not _bool(route_locked)
        and not _bool(force_requested_runtime)
        and not requires_approval
        and not external_risk
        and not destructive_risk
        and not high_risk
        and not route_is_frontier
    )
    if deterministic_allowed:
        reason = (
            "trusted_deterministic_status"
            if normalized_kind == "status"
            else "trusted_deterministic_command"
        )
        return _contract("deterministic", [reason])

    if requires_approval or external_risk or destructive_risk or high_risk:
        reasons: list[str] = []
        if requires_approval:
            reasons.append("trusted_approval_requirement")
        if external_risk:
            reasons.append("external_mutation")
        if destructive_risk:
            reasons.append("destructive_risk")
        if high_risk and "destructive_risk" not in reasons:
            reasons.append("high_risk")
        return _contract("approval_required", reasons)

    if route_is_frontier:
        reasons = []
        if _bool(force_requested_runtime):
            reasons.append("forced_frontier_route")
        if _bool(route_locked):
            reasons.append("locked_frontier_route")
        if effective_frontier:
            reasons.append("effective_frontier_runtime")
        return _contract("frontier", reasons)

    review_reason = {
        "code": "local_review_code",
        "judge": "local_review_verify",
        "kpi": "local_review_kpi",
        "plan": "local_review_plan",
        "scout": "local_review_scout",
        "verify": "local_review_verify",
    }.get(normalized_task_kind)
    if review_reason or normalized_task_kind in _LOCAL_REVIEW_TASK_KINDS:
        return _contract("local_review", [review_reason or "local_review_verify"])

    return _contract("local", ["local_safe_analysis"])


def sanitize_work_classification(value: Any) -> dict[str, Any]:
    """Return a verified classification contract or an empty mapping.

    This rejects unknown fields as values only through the required contract
    checks. It intentionally does not retain caller-provided rationale text.
    """

    payload = _as_mapping(value)
    work_class = _clean(payload.get("work_class"))
    if (
        payload.get("schema") != WORK_CLASSIFICATION_SCHEMA
        or work_class not in _WORK_CLASS_PROPERTIES
    ):
        return {}
    reason_codes = payload.get("reason_codes")
    if (
        not isinstance(reason_codes, list)
        or not reason_codes
        or len(reason_codes) > 4
        or any(not isinstance(reason, str) for reason in reason_codes)
    ):
        return {}
    normalized_reasons = [_clean(reason) for reason in reason_codes]
    if (
        any(reason not in _VALID_REASON_CODES for reason in normalized_reasons)
        or len(set(normalized_reasons)) != len(normalized_reasons)
        or not set(normalized_reasons) & _REQUIRED_REASON_CODES[work_class]
    ):
        return {}
    expected = _contract(work_class, normalized_reasons)
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            return {}
    return expected
