"""Conservative per-model lane policy for benchmark-backed local routing."""

from __future__ import annotations

from typing import Any

LANE_POLICY_SCHEMA = "norman.norllama.lane-policy.v1"

_QWEN_DEFAULT = {
    "model_family": "qwen",
    "allowed_lanes": {
        "planner",
        "scout",
        "summarizer",
        "filter",
        "coder",
        "verifier",
        "judge",
    },
    "route_mode": "local_draft_with_verifier",
    "requires_deterministic_verifier": True,
    "requires_cloud_final_for_actions": True,
    "selection_reason": "Qwen remains Norman's general local routing floor.",
}

_GPT_OSS_CODE = {
    "model_family": "gpt_oss",
    "allowed_lanes": {"coder"},
    "route_mode": "code_draft_with_verifier",
    "requires_deterministic_verifier": True,
    "requires_cloud_final_for_actions": True,
    "selection_reason": (
        "GPT-OSS is permitted for code drafting only; benchmark contract and "
        "safety failures require deterministic checks plus final verification."
    ),
}

_DEEPSEEK_CODE = {
    "model_family": "deepseek",
    "allowed_lanes": {"coder"},
    "route_mode": "code_draft_with_verifier",
    "requires_deterministic_verifier": True,
    "requires_cloud_final_for_actions": True,
    "selection_reason": (
        "DeepSeek is permitted for code drafting only; use deterministic checks "
        "and final verification before any action."
    ),
}

_GEMMA_STRUCTURED = {
    "model_family": "gemma",
    "allowed_lanes": {"filter", "summarizer"},
    "route_mode": "structured_draft_with_verifier",
    "requires_deterministic_verifier": True,
    "requires_cloud_final_for_actions": True,
    "selection_reason": (
        "Gemma may assist bounded structured work only; semantic quality is "
        "not execution or authority proof."
    ),
}

_UNKNOWN = {
    "model_family": "unknown",
    "allowed_lanes": {
        "embedding",
        "rerank",
        "safety",
        "prompt_injection",
        "ocr",
        "doc_parse",
        "gui_ground",
        "speech",
        "forecast",
        "graph",
        "network",
        "world",
    },
    "route_mode": "bounded_specialist_with_verifier",
    "requires_deterministic_verifier": True,
    "requires_cloud_final_for_actions": True,
    "selection_reason": (
        "Unrecognized local models are eligible only for explicit bounded "
        "specialist lanes."
    ),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _model_policy(model: str) -> dict[str, Any]:
    lowered = _clean(model).lower()
    if "gpt-oss" in lowered or "gpt_oss" in lowered or "gptoss" in lowered:
        return _GPT_OSS_CODE
    if "deepseek" in lowered:
        return _DEEPSEEK_CODE
    if "gemma" in lowered:
        return _GEMMA_STRUCTURED
    if "qwen" in lowered:
        return _QWEN_DEFAULT
    return _UNKNOWN


def lane_policy_for_model(
    *,
    model: str,
    lane: str,
    benchmark_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a hard local-use contract for one model/lane selection."""

    policy = _model_policy(model)
    lane_name = _clean(lane).lower()
    quality = benchmark_quality if isinstance(benchmark_quality, dict) else {}
    quality_eligible = bool(quality.get("eligible", True))
    allowed_lanes = policy["allowed_lanes"]
    lane_allowed = allowed_lanes is None or lane_name in allowed_lanes
    allowed = bool(lane_name and lane_allowed and quality_eligible)
    reason = _clean(policy["selection_reason"])
    if not quality_eligible:
        reason = _clean(quality.get("reason")) or "benchmark quality gate blocked model"
    elif not lane_name:
        reason = "model selection did not resolve a routing lane"
    elif policy["model_family"] == "unknown" and not lane_allowed:
        reason = "unknown local model has no default production lane"
    elif allowed_lanes is not None and lane_name not in allowed_lanes:
        reason = (
            f"{policy['model_family']} is not eligible for local {lane_name} routing"
        )
    return {
        "schema": LANE_POLICY_SCHEMA,
        "model": _clean(model),
        "model_family": policy["model_family"],
        "lane": lane_name,
        "allowed": allowed,
        "route_mode": policy["route_mode"] if allowed else "blocked",
        "requires_deterministic_verifier": bool(
            policy["requires_deterministic_verifier"]
        ),
        "requires_cloud_final_for_actions": bool(
            policy["requires_cloud_final_for_actions"]
        ),
        "final_authority": False,
        "reason": reason,
    }
