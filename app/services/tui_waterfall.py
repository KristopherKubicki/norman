"""Sanitized routing waterfall for Norman web TUIs.

The caller may inspect provider and Norllama health locally, but only this
generic result is allowed to cross a TUI persistence boundary.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "norman.tui-waterfall.v1"
BEDROCK_EMERGENCY_TIERS = (
    "bedrock-emergency",
    "bedrock-failover",
    "bedrock-failover-2",
)
_CAPACITY_STATES = {"available", "blocked", "unknown"}
_STAGES = {
    "subscription_flex",
    "subscription_flex_probe",
    "norllama_pool",
    "bedrock_verified_exhaustion",
    "bedrock_direct_limit_recovery",
    "bedrock_manual",
    "route_lock",
    "deterministic_status",
    "deterministic_command",
    "blocked",
    "blocked_manual_bedrock",
}
_BEDROCK_RETRY_STAGES = {"bedrock_verified_exhaustion"}
_STAGE_METADATA = {
    "subscription_flex": {
        "route_source": "subscription_capacity",
        "reason": "fresh verified ChatGPT subscription capacity selected Flex",
        "fallback_reason": "",
        "charge_basis": "chatgpt_codex_credit_estimate",
        "attempts": ("subscription_flex",),
    },
    "subscription_flex_probe": {
        "route_source": "subscription_capacity_probe",
        "reason": (
            "verified ChatGPT authentication selected one guarded Flex capacity probe"
        ),
        "fallback_reason": "",
        "charge_basis": "chatgpt_codex_credit_estimate",
        "attempts": ("subscription_flex_probe",),
    },
    "norllama_pool": {
        "route_source": "norllama_pool",
        "reason": "verified subscription exhaustion selected the Norllama pool",
        "fallback_reason": "verified_subscription_exhaustion",
        "charge_basis": "local_token_estimate",
        "attempts": ("subscription_flex", "norllama_pool"),
    },
    "bedrock_verified_exhaustion": {
        "route_source": "bedrock_verified_exhaustion",
        "reason": (
            "verified subscription exhaustion and no safe Norllama route "
            "authorized Bedrock"
        ),
        "fallback_reason": "verified_subscription_exhaustion",
        "charge_basis": "provider_invoice_estimate",
        "attempts": (
            "subscription_flex",
            "norllama_pool",
            "bedrock_verified_exhaustion",
        ),
    },
    "bedrock_direct_limit_recovery": {
        "route_source": "direct_tier_usage_limit_recovery",
        "reason": "recent direct-tier usage limit selected Bedrock default",
        "fallback_reason": "recent_direct_tier_usage_limit",
        "charge_basis": "provider_invoice_estimate",
        "attempts": ("direct_tier_usage_limit_recovery",),
    },
    "bedrock_manual": {
        "route_source": "operator_route_lock",
        "reason": "operator selected the Bedrock route",
        "fallback_reason": "",
        "charge_basis": "provider_invoice_estimate",
        "attempts": ("bedrock_manual",),
    },
    "route_lock": {
        "route_source": "operator_route_lock",
        "reason": "operator route lock retained the requested route",
        "fallback_reason": "",
        "charge_basis": "manual_route",
        "attempts": ("route_lock",),
    },
    "deterministic_status": {
        "route_source": "deterministic_tui_status",
        "reason": "durable TUI state answered status without a model call",
        "fallback_reason": "",
        "charge_basis": "zero_token_deterministic",
        "attempts": ("deterministic_status",),
    },
    "deterministic_command": {
        "route_source": "deterministic_tui_command",
        "reason": "fixed read-only TUI command executed without a model call",
        "fallback_reason": "",
        "charge_basis": "zero_token_deterministic",
        "attempts": ("deterministic_command",),
    },
    "blocked": {
        "route_source": "waterfall_guard",
        "reason": (
            "automatic Bedrock fallback requires fresh verified ChatGPT "
            "subscription exhaustion and no eligible Norllama route"
        ),
        "fallback_reason": "",
        "charge_basis": "blocked",
        "attempts": ("subscription_flex",),
    },
    "blocked_manual_bedrock": {
        "route_source": "waterfall_guard",
        "reason": "operator-selected Bedrock route is not configured",
        "fallback_reason": "",
        "charge_basis": "blocked",
        "attempts": ("route_lock",),
    },
}
_ALLOWED_KEYS = (
    "schema",
    "selected",
    "blocked",
    "requested_runtime",
    "requested_model",
    "requested_service_tier",
    "selected_runtime",
    "selected_model",
    "selected_service_tier",
    "stage",
    "waterfall_stage",
    "route_source",
    "reason",
    "fallback_reason",
    "attempts",
    "waterfall_attempt_count",
    "route_lock",
    "bedrock_auto_authorized",
    "subscription_capacity",
    "charge_basis",
    "direct_tier_usage_limit_recovery",
    "norllama_pool",
    "local_final_authority",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_named_bedrock_emergency_tier(value: Any) -> bool:
    return _text(value).lower() in BEDROCK_EMERGENCY_TIERS


def _capacity_summary(subscription: dict[str, Any]) -> dict[str, Any]:
    state = _text(subscription.get("state")).lower()
    if state not in _CAPACITY_STATES:
        state = "unknown"
    return {
        "enabled": bool(subscription.get("enabled")),
        "selected": bool(subscription.get("selected")),
        "state": state,
        "fresh": bool(subscription.get("fresh")),
        "chatgpt_auth_verified": bool(subscription.get("chatgpt_auth_verified")),
    }


def sanitize_tui_waterfall_decision(value: Any) -> dict[str, Any]:
    """Return the only route shape permitted in TUI durable state.

    Provider probes may include pool members, endpoint health, candidates, and
    retry internals. Those details are useful only while selecting a route and
    must never be serialized into status, queues, envelopes, or receipts.
    """

    source = value if isinstance(value, dict) else {}
    stage = _text(source.get("waterfall_stage") or source.get("stage")).lower()
    if stage not in _STAGES:
        return {}
    source_stage = _text(source.get("stage")).lower()
    source_waterfall_stage = _text(source.get("waterfall_stage")).lower()
    if (
        source_stage
        and source_waterfall_stage
        and source_stage != source_waterfall_stage
    ):
        return {}
    subscription = _capacity_summary(
        source.get("subscription_capacity")
        if isinstance(source.get("subscription_capacity"), dict)
        else {}
    )
    selected = source.get("selected") is True
    unblocked = source.get("blocked") is False
    selected_runtime = _text(source.get("selected_runtime"))
    selected_model = _text(source.get("selected_model"))
    selected_service_tier = _text(source.get("selected_service_tier"))
    route_lock = source.get("route_lock") is True

    if stage in {"blocked", "blocked_manual_bedrock"}:
        if selected or source.get("blocked") is not True:
            return {}
    elif not selected or not unblocked:
        return {}

    if stage in {"subscription_flex", "subscription_flex_probe"} and not (
        selected_runtime == "codex"
        and selected_service_tier == "flex"
        and selected_model
    ):
        return {}
    if stage == "subscription_flex" and not (
        subscription["enabled"]
        and subscription["selected"]
        and subscription["state"] == "available"
        and subscription["fresh"]
        and subscription["chatgpt_auth_verified"]
    ):
        return {}
    if stage == "subscription_flex_probe" and not (
        subscription["enabled"]
        and subscription["chatgpt_auth_verified"]
        and (not subscription["fresh"] or subscription["state"] == "unknown")
    ):
        return {}
    if stage == "norllama_pool" and not (
        selected_runtime == "localllm"
        and selected_model == "norllama"
        and selected_service_tier == "default"
        and source.get("norllama_pool") == "default"
        and source.get("local_final_authority") is True
    ):
        return {}
    if stage in {"bedrock_verified_exhaustion", "bedrock_manual"} and not (
        selected_runtime == "codex"
        and _is_named_bedrock_emergency_tier(selected_service_tier)
        and selected_model
    ):
        return {}
    if stage == "bedrock_direct_limit_recovery" and not (
        _text(source.get("requested_runtime")) == "codex"
        and _text(source.get("requested_service_tier")) in {"flex", "priority"}
        and selected_runtime == "codex"
        and selected_service_tier == "default"
        and selected_model
        and not route_lock
        and source.get("direct_tier_usage_limit_recovery") is True
    ):
        return {}
    if stage == "bedrock_manual" and not route_lock:
        return {}
    if stage == "bedrock_verified_exhaustion" and not (
        subscription["enabled"]
        and subscription["state"] == "blocked"
        and subscription["fresh"]
        and subscription["chatgpt_auth_verified"]
        and not route_lock
    ):
        return {}
    if stage == "route_lock" and not (
        route_lock and selected_runtime and selected_model and selected_service_tier
    ):
        return {}
    if stage in {"deterministic_status", "deterministic_command"}:
        expected_model = (
            "deterministic-status"
            if stage == "deterministic_status"
            else "deterministic-command"
        )
        if not (
            _text(source.get("requested_runtime")) == "localllm"
            and _text(source.get("requested_model")) == expected_model
            and _text(source.get("requested_service_tier")) == "default"
            and selected_runtime == "localllm"
            and selected_model == expected_model
            and selected_service_tier == "default"
            and not route_lock
        ):
            return {}
    if stage == "deterministic_status" and selected_model != "deterministic-status":
        return {}
    if stage == "deterministic_command" and selected_model != "deterministic-command":
        return {}

    metadata = _STAGE_METADATA[stage]
    attempts = list(metadata["attempts"])
    if stage == "blocked" and (
        subscription["selected"]
        and subscription["state"] == "blocked"
        and subscription["fresh"]
        and subscription["chatgpt_auth_verified"]
    ):
        attempts.append("norllama_pool")
    result = {
        "schema": SCHEMA,
        "selected": selected and stage != "blocked",
        "blocked": source.get("blocked") is True or stage == "blocked",
        "requested_runtime": _text(source.get("requested_runtime")),
        "requested_model": _text(source.get("requested_model")),
        "requested_service_tier": _text(source.get("requested_service_tier")),
        "selected_runtime": selected_runtime,
        "selected_model": selected_model,
        "selected_service_tier": selected_service_tier,
        "stage": stage,
        "waterfall_stage": stage,
        "route_source": metadata["route_source"],
        "reason": metadata["reason"],
        "fallback_reason": metadata["fallback_reason"],
        "attempts": attempts,
        "waterfall_attempt_count": len(attempts),
        "route_lock": stage in {"bedrock_manual", "route_lock"},
        "bedrock_auto_authorized": stage
        in {"bedrock_verified_exhaustion", "bedrock_direct_limit_recovery"},
        "subscription_capacity": subscription,
        "charge_basis": metadata["charge_basis"],
    }
    if result["blocked"]:
        result["selected"] = False
        result["selected_runtime"] = ""
        result["selected_model"] = ""
        result["selected_service_tier"] = ""
    if stage == "norllama_pool":
        result.update(
            {
                "selected": True,
                "blocked": False,
                "selected_runtime": "localllm",
                "selected_model": "norllama",
                "selected_service_tier": "default",
                "norllama_pool": "default",
                "local_final_authority": True,
            }
        )
    elif stage in {"subscription_flex", "subscription_flex_probe"}:
        result.update(
            {
                "selected": True,
                "blocked": False,
                "selected_runtime": "codex",
                "selected_service_tier": "flex",
            }
        )
    elif stage in _BEDROCK_RETRY_STAGES:
        result.update(
            {
                "selected": True,
                "blocked": False,
                "selected_runtime": "codex",
            }
        )
    elif stage == "bedrock_direct_limit_recovery":
        result.update(
            {
                "selected": True,
                "blocked": False,
                "selected_runtime": "codex",
                "selected_service_tier": "default",
                "direct_tier_usage_limit_recovery": True,
            }
        )
    return {key: result[key] for key in _ALLOWED_KEYS if key in result}


def waterfall_allows_bedrock_retry(value: Any) -> bool:
    """Return whether a route is authorized to mutate within Bedrock retries."""

    decision = sanitize_tui_waterfall_decision(value)
    return bool(
        decision.get("selected")
        and decision.get("waterfall_stage") in _BEDROCK_RETRY_STAGES
    )


def _decision(
    *,
    requested_runtime: str,
    requested_model: str,
    requested_service_tier: str,
    selected: bool,
    blocked: bool,
    selected_runtime: str,
    selected_model: str,
    selected_service_tier: str,
    stage: str,
    route_source: str,
    reason: str,
    fallback_reason: str,
    attempts: list[str],
    route_lock: bool,
    bedrock_auto_authorized: bool,
    subscription_capacity: dict[str, Any],
    charge_basis: str,
    direct_tier_usage_limit_recovery: bool = False,
    norllama: bool = False,
) -> dict[str, Any]:
    result = {
        "schema": SCHEMA,
        "selected": selected,
        "blocked": blocked,
        "requested_runtime": requested_runtime,
        "requested_model": requested_model,
        "requested_service_tier": requested_service_tier,
        "selected_runtime": selected_runtime,
        "selected_model": selected_model,
        "selected_service_tier": selected_service_tier,
        "stage": stage,
        "waterfall_stage": stage,
        "route_source": route_source,
        "reason": reason,
        "fallback_reason": fallback_reason,
        "attempts": attempts,
        "waterfall_attempt_count": len(attempts),
        "route_lock": route_lock,
        "bedrock_auto_authorized": bedrock_auto_authorized,
        "subscription_capacity": subscription_capacity,
        "charge_basis": charge_basis,
    }
    if direct_tier_usage_limit_recovery:
        result["direct_tier_usage_limit_recovery"] = True
    if norllama:
        result["norllama_pool"] = "default"
        result["local_final_authority"] = True
    return sanitize_tui_waterfall_decision(result)


def build_tui_waterfall(
    *,
    requested_runtime: str,
    requested_model: str,
    requested_service_tier: str,
    base_runtime: str,
    base_model: str,
    base_service_tier: str,
    bedrock_runtime: str,
    bedrock_model: str,
    bedrock_service_tier: str,
    route_lock: bool,
    subscription: dict[str, Any],
    norllama_available: bool,
    norllama_safe_final: bool,
    bedrock_available: bool,
    manual_bedrock_available: bool | None = None,
    direct_tier_usage_limit_recovery: bool = False,
    deterministic_status: bool = False,
    deterministic_command: bool = False,
) -> dict[str, Any]:
    """Choose the only automatic path from ChatGPT capacity to Bedrock.

    `subscription` may be a richer local decision. This function deliberately
    reads only its generic eligibility booleans and never returns its contents.
    """

    requested_runtime = _text(requested_runtime)
    requested_model = _text(requested_model)
    requested_service_tier = _text(requested_service_tier)
    base_runtime = _text(base_runtime)
    base_model = _text(base_model)
    base_service_tier = _text(base_service_tier)
    bedrock_runtime = _text(bedrock_runtime)
    bedrock_model = _text(bedrock_model)
    bedrock_service_tier = _text(bedrock_service_tier)
    capacity = _capacity_summary(subscription)
    subscription_enabled = bool(subscription.get("enabled"))

    # A deliberately chosen Bedrock route remains an operator decision, not an
    # automatic paid fallback.
    manual_bedrock_available = (
        bool(bedrock_available)
        if manual_bedrock_available is None
        else bool(manual_bedrock_available)
    )
    if deterministic_status and deterministic_command:
        return {}
    if deterministic_status:
        if not (
            requested_runtime == base_runtime == "localllm"
            and requested_model == base_model == "deterministic-status"
            and base_service_tier == "default"
        ):
            return {}
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="localllm",
            selected_model="deterministic-status",
            selected_service_tier="default",
            stage="deterministic_status",
            route_source="deterministic_tui_status",
            reason="durable TUI state answered status without a model call",
            fallback_reason="",
            attempts=["deterministic_status"],
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="zero_token_deterministic",
        )
    if deterministic_command:
        if not (
            requested_runtime == base_runtime == "localllm"
            and requested_model == base_model == "deterministic-command"
            and base_service_tier == "default"
        ):
            return {}
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="localllm",
            selected_model="deterministic-command",
            selected_service_tier="default",
            stage="deterministic_command",
            route_source="deterministic_tui_command",
            reason="fixed read-only TUI command executed without a model call",
            fallback_reason="",
            attempts=["deterministic_command"],
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="zero_token_deterministic",
        )

    if (
        route_lock
        and requested_runtime == base_runtime == "codex"
        and requested_service_tier == base_service_tier
        and _is_named_bedrock_emergency_tier(base_service_tier)
        and manual_bedrock_available
    ):
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="codex",
            selected_model=base_model,
            selected_service_tier=base_service_tier,
            stage="bedrock_manual",
            route_source="operator_route_lock",
            reason="operator selected the Bedrock route",
            fallback_reason="",
            attempts=["bedrock_manual"],
            route_lock=True,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="provider_invoice_estimate",
        )

    if (
        route_lock
        and requested_runtime == base_runtime == "codex"
        and requested_service_tier == base_service_tier
        and _is_named_bedrock_emergency_tier(base_service_tier)
    ):
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=False,
            blocked=True,
            selected_runtime="",
            selected_model="",
            selected_service_tier="",
            stage="blocked_manual_bedrock",
            route_source="waterfall_guard",
            reason="operator-selected Bedrock route is not configured",
            fallback_reason="",
            attempts=["route_lock"],
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="blocked",
        )

    if route_lock:
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime=base_runtime,
            selected_model=base_model,
            selected_service_tier=base_service_tier,
            stage="route_lock",
            route_source="operator_route_lock",
            reason="operator route lock retained the requested route",
            fallback_reason="",
            attempts=["route_lock"],
            route_lock=True,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="manual_route",
        )

    if (
        direct_tier_usage_limit_recovery
        and requested_runtime == "codex"
        and requested_service_tier in {"flex", "priority"}
        and base_runtime == "codex"
        and base_service_tier == "default"
        and base_model
    ):
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="codex",
            selected_model=base_model,
            selected_service_tier="default",
            stage="bedrock_direct_limit_recovery",
            route_source="direct_tier_usage_limit_recovery",
            reason="recent direct-tier usage limit selected Bedrock default",
            fallback_reason="recent_direct_tier_usage_limit",
            attempts=["direct_tier_usage_limit_recovery"],
            route_lock=False,
            bedrock_auto_authorized=True,
            subscription_capacity=capacity,
            charge_basis="provider_invoice_estimate",
            direct_tier_usage_limit_recovery=True,
        )

    # The local subscription selector has already verified forecast, reserve,
    # lane eligibility, and current authentication. Honor a positive result.
    if (
        capacity["selected"]
        and subscription_enabled
        and capacity["state"] == "available"
        and capacity["fresh"]
        and capacity["chatgpt_auth_verified"]
    ):
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="codex",
            selected_model=base_model,
            selected_service_tier="flex",
            stage="subscription_flex",
            route_source="subscription_capacity",
            reason="fresh verified ChatGPT subscription capacity selected Flex",
            fallback_reason="",
            attempts=["subscription_flex"],
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="chatgpt_codex_credit_estimate",
        )

    if (
        subscription_enabled
        and capacity["chatgpt_auth_verified"]
        and (not capacity["fresh"] or capacity["state"] == "unknown")
    ):
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="codex",
            selected_model=base_model,
            selected_service_tier="flex",
            stage="subscription_flex_probe",
            route_source="subscription_capacity_probe",
            reason=(
                "verified ChatGPT authentication selected one guarded Flex "
                "capacity probe"
            ),
            fallback_reason="",
            attempts=["subscription_flex_probe"],
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="chatgpt_codex_credit_estimate",
        )

    verified_exhaustion = bool(
        subscription_enabled
        and capacity["state"] == "blocked"
        and capacity["fresh"]
        and capacity["chatgpt_auth_verified"]
    )
    attempts = ["subscription_flex"]
    if verified_exhaustion and norllama_available and norllama_safe_final:
        attempts.append("norllama_pool")
        return _decision(
            requested_runtime=requested_runtime,
            requested_model=requested_model,
            requested_service_tier=requested_service_tier,
            selected=True,
            blocked=False,
            selected_runtime="localllm",
            selected_model="norllama",
            selected_service_tier="default",
            stage="norllama_pool",
            route_source="norllama_pool",
            reason="verified subscription exhaustion selected the Norllama pool",
            fallback_reason="verified_subscription_exhaustion",
            attempts=attempts,
            route_lock=False,
            bedrock_auto_authorized=False,
            subscription_capacity=capacity,
            charge_basis="local_token_estimate",
            norllama=True,
        )

    if verified_exhaustion:
        attempts.append("norllama_pool")
        if bedrock_available and _is_named_bedrock_emergency_tier(bedrock_service_tier):
            attempts.append("bedrock_verified_exhaustion")
            return _decision(
                requested_runtime=requested_runtime,
                requested_model=requested_model,
                requested_service_tier=requested_service_tier,
                selected=True,
                blocked=False,
                selected_runtime=bedrock_runtime,
                selected_model=bedrock_model,
                selected_service_tier=bedrock_service_tier,
                stage="bedrock_verified_exhaustion",
                route_source="bedrock_verified_exhaustion",
                reason=(
                    "verified subscription exhaustion and no safe Norllama "
                    "route authorized Bedrock"
                ),
                fallback_reason="verified_subscription_exhaustion",
                attempts=attempts,
                route_lock=False,
                bedrock_auto_authorized=True,
                subscription_capacity=capacity,
                charge_basis="provider_invoice_estimate",
            )

    return _decision(
        requested_runtime=requested_runtime,
        requested_model=requested_model,
        requested_service_tier=requested_service_tier,
        selected=False,
        blocked=True,
        selected_runtime="",
        selected_model="",
        selected_service_tier="",
        stage="blocked",
        route_source="waterfall_guard",
        reason=(
            "automatic Bedrock fallback requires fresh verified ChatGPT "
            "subscription exhaustion and no eligible Norllama route"
        ),
        fallback_reason="",
        attempts=attempts,
        route_lock=False,
        bedrock_auto_authorized=False,
        subscription_capacity=capacity,
        charge_basis="blocked",
    )
