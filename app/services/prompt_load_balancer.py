import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.types import NorllamaTaskKind, NorllamaTaskRequest
from app.services.reasoning_orchestrator import (
    build_reasoning_receipt,
    build_skill_registry,
    kpi_background_loop_plan,
    plan_reasoning_turn,
)
from app.services import tui_route_intent

PROMPT_LOAD_BALANCER_SCHEMA = "norman.prompt-load-balancer.v1"
PROMPT_ROUTE_RECEIPT_SCHEMA = "norman.prompt-load-balancer.receipt.v1"
PROMPT_PROVIDER_ADAPTER_SCHEMA = "norman.prompt-provider-adapter.v1"

_TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "force"}
_CLOUD_RUNTIMES = {"aws-bedrock", "bedrock", "codex", "openai", "openai-direct"}
_LOCAL_RUNTIMES = {"local", "localllm", "norllama", "ollama", "openai-compatible"}
_CONTINUE_PHRASES = (
    *tui_route_intent.PROCEED_PHRASES,
    "keep working",
    "lets go",
    "let's go",
)
_RETRY_PHRASES = tui_route_intent.RETRY_PHRASES
_STOP_PHRASES = tui_route_intent.STOP_PHRASES
_UNDO_PHRASES = tui_route_intent.UNDO_PHRASES
_SHIP_PHRASES = tui_route_intent.SHIP_PHRASES
_RESTART_PHRASES = tui_route_intent.RESTART_PHRASES
_NEXT_PHRASES = (
    "what is next",
    "what's next",
    "whats next",
    "next steps",
    "what do you want to do",
)
_WEB_RESEARCH_WORDS = {
    "browse",
    "internet",
    "latest",
    "look up",
    "perplexity",
    "price",
    "research",
    "search",
    "today",
    "wayback",
    "web",
}
_CODE_WORDS = {
    "code",
    "commit",
    "diff",
    "fix",
    "implement",
    "patch",
    "repo",
    "test",
    "tests",
}
_VERIFY_WORDS = {
    "audit",
    "check",
    "prove",
    "review",
    "verify",
    "validate",
}
_DESTRUCTIVE_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bdrop\s+database\b",
    r"\bfactory\s+reset\b",
    r"\bformat\s+disk\b",
    r"\bwipe\b",
)
_EXTERNAL_MUTATION_WORDS = {
    "deploy",
    "firewall",
    "merge",
    "power cycle",
    "push",
    "reboot",
    "release",
    "restart",
    "systemctl",
}
_LOCAL_MUTATION_WORDS = {
    "add",
    "change",
    "edit",
    "fix",
    "implement",
    "patch",
    "refactor",
    "rollback",
    "undo",
    "write",
}
_SECRET_WORDS = {"credential", "key", "password", "secret", "token"}
_HIGH_REASONING_WORDS = {
    "architecture",
    "audit",
    "benchmark",
    "degraded",
    "design",
    "failover",
    "judge",
    "migration",
    "outlier",
    "policy",
    "proof",
    "release",
    "rollback",
    "routing",
    "security",
    "verify",
}
_DETERMINISTIC_INTENTS = {
    "continue_work",
    "copy_response",
    "next_steps",
    "quick_status",
    "retry_last_step",
    "simplify_response",
    "stop_or_pause",
}
_SPECIALIST_TASK_KINDS = {
    NorllamaTaskKind.ASR.value,
    NorllamaTaskKind.DOC_PARSE.value,
    NorllamaTaskKind.OCR.value,
    NorllamaTaskKind.RERANK.value,
}
_ADAPTER_MODES = {
    "route_only": {
        "label": "Route Only",
        "enforcement_level": "decision_only",
        "client_action": "execute_selected_route_or_call_norman_execution_endpoint",
        "mutates_request": False,
        "blocks_request": False,
        "uses_local_intelligence": True,
    },
    "transparent_log_only": {
        "label": "Transparent Log Only",
        "enforcement_level": "observe_only",
        "client_action": "forward_original_provider_request_after_recording_route_receipt",
        "mutates_request": False,
        "blocks_request": False,
        "uses_local_intelligence": False,
    },
    "guardrail": {
        "label": "Guardrail",
        "enforcement_level": "policy_block_or_approval",
        "client_action": "block_or_hold_policy_violations_else_forward_selected_route",
        "mutates_request": False,
        "blocks_request": True,
        "uses_local_intelligence": True,
    },
    "intelligence": {
        "label": "Intelligence",
        "enforcement_level": "active_route_optimization",
        "client_action": "execute_norman_selected_local_first_route",
        "mutates_request": True,
        "blocks_request": True,
        "uses_local_intelligence": True,
    },
    "shadow_compare": {
        "label": "Shadow Compare",
        "enforcement_level": "observe_plus_shadow",
        "client_action": "forward_original_request_and_run_local_shadow_when_available",
        "mutates_request": False,
        "blocks_request": False,
        "uses_local_intelligence": True,
    },
    "strict_local": {
        "label": "Strict Local",
        "enforcement_level": "cloud_blocked",
        "client_action": "execute_local_route_or_return_explicit_degraded_block",
        "mutates_request": True,
        "blocks_request": True,
        "uses_local_intelligence": True,
    },
}
_ADAPTER_MODE_ALIASES = {
    "audit": "transparent_log_only",
    "intelligent": "intelligence",
    "log": "transparent_log_only",
    "log_only": "transparent_log_only",
    "monitor": "transparent_log_only",
    "observe": "transparent_log_only",
    "observe_only": "transparent_log_only",
    "shadow": "shadow_compare",
    "strict": "strict_local",
    "transparent": "transparent_log_only",
}


def _console_runtime_policy_helpers():
    from app.services.console_runtime.policy import (
        resolve_runtime_mode,
        route_decision,
        with_local_first_catalog_defaults,
    )

    return resolve_runtime_mode, route_decision, with_local_first_catalog_defaults


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
    if clean in _TRUE_VALUES:
        return True
    if clean in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _future_timestamp(value: Any) -> bool:
    clean = _clean(value)
    if not clean:
        return False
    try:
        if clean.isdigit():
            return int(clean) > int(datetime.now(timezone.utc).timestamp())
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)


def _stateful_terse_control(
    *,
    classification: Mapping[str, Any],
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    intent = _clean(classification.get("intent"))
    active_job_count = _integer(ctx.get("active_job_count"))
    pending_action_digest = _clean(ctx.get("pending_action_digest"))
    pending_action_risk = _lower(ctx.get("pending_action_risk"))
    pending_action_kind = _clean(ctx.get("pending_action_kind"))
    target_identity = _clean(ctx.get("target_identity") or ctx.get("active_job_id"))
    approval_id = _clean(ctx.get("approval_id"))
    approval_expires_at = _clean(ctx.get("approval_expires_at"))
    approval_valid = bool(approval_id and _future_timestamp(approval_expires_at))
    terse_control = intent in {
        "continue_work",
        "retry_last_step",
        "stop_or_pause",
        "undo_or_rollback",
        "restart_or_recover",
        "ship_or_release",
        "copy_response",
        "handoff_or_relay",
    }
    risky_pending = pending_action_risk in {
        "prod_write",
        "external_mutation",
        "destructive",
        "critical",
        "high",
    }
    mutating_intent = intent in {
        "undo_or_rollback",
        "restart_or_recover",
        "ship_or_release",
    }
    blockers: list[str] = []
    selected_action = intent or "general_prompt"
    tool_selection = "none"
    if intent == "stop_or_pause":
        selected_action = "deterministic_stop_current_job"
        tool_selection = "console_control"
    elif intent == "copy_response":
        selected_action = "deterministic_copy_latest_response"
        tool_selection = "browser_ui"
    elif intent == "handoff_or_relay":
        selected_action = pending_action_kind or "prepare_bound_handoff"
        tool_selection = "relay_broker"
    elif terse_control:
        selected_action = pending_action_kind or intent
        tool_selection = "console_runtime_kernel"
    if terse_control and intent not in {"stop_or_pause", "copy_response"}:
        if active_job_count <= 0:
            blockers.append("no_active_job_bound_to_terse_command")
        elif active_job_count > 1:
            blockers.append("multiple_active_jobs_require_target_selection")
        if not target_identity:
            blockers.append("missing_target_identity")
        if (risky_pending or mutating_intent) and not pending_action_digest:
            blockers.append("missing_pending_action_digest")
        if (risky_pending or mutating_intent) and not approval_valid:
            blockers.append("missing_valid_bound_approval")
    execution_allowed = not blockers
    requires_approval = bool(blockers and (risky_pending or mutating_intent))
    if terse_control and blockers and not requires_approval:
        requires_approval = True
    return {
        "schema": "norman.prompt-load-balancer.stateful-control.v1",
        "applies": terse_control,
        "selected_action": selected_action,
        "execution_allowed": execution_allowed,
        "execution_permission": "allowed" if execution_allowed else "blocked",
        "requires_approval": requires_approval,
        "approval_binding": {
            "approval_id": approval_id,
            "approval_valid": approval_valid,
            "approval_expires_at": approval_expires_at,
            "pending_action_digest": pending_action_digest,
            "pending_action_risk": pending_action_risk,
        },
        "target_identity": target_identity,
        "tool_selection": tool_selection,
        "route": "local_control_prefilter",
        "visible_response": (
            "blocked_until_bound_approval"
            if blockers
            else "terse_command_bound_to_current_state"
        ),
        "receipt": {
            "required": True,
            "fields": [
                "selected_action",
                "execution_permission",
                "approval_binding",
                "target_identity",
                "tool_selection",
                "route",
                "visible_response",
            ],
        },
        "blockers": blockers,
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _word_tokens(text: str) -> list[str]:
    return tui_route_intent.word_tokens(text)


def _contains_any(text: str, needles: set[str] | tuple[str, ...]) -> bool:
    return tui_route_intent.contains_any(text, needles)


def _looks_like_status_word(token: str) -> bool:
    return tui_route_intent.looks_like_status_word(token)


def _has_status_signal(text: str) -> bool:
    return tui_route_intent.has_status_signal(text)


def _quick_status(text: str) -> bool:
    return tui_route_intent.is_quick_status(text)


def _artifact_task_kind(artifacts: list[dict[str, Any]]) -> str:
    for artifact in artifacts:
        kind = _lower(
            artifact.get("kind")
            or artifact.get("type")
            or artifact.get("content_type")
            or artifact.get("media_type")
        )
        name = _lower(
            artifact.get("name") or artifact.get("path") or artifact.get("url")
        )
        value = f"{kind} {name}"
        if any(
            marker in value for marker in ("audio", ".wav", ".mp3", ".m4a", ".flac")
        ):
            return NorllamaTaskKind.ASR.value
        if any(
            marker in value for marker in ("image", ".png", ".jpg", ".jpeg", ".webp")
        ):
            return NorllamaTaskKind.OCR.value
        if any(marker in value for marker in ("pdf", ".pdf", "document")):
            return NorllamaTaskKind.DOC_PARSE.value
    return ""


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("input_text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part and part.strip())
    if isinstance(value, Mapping):
        text = value.get("text") or value.get("input_text")
        return str(text or "").strip()
    return ""


def _messages_prompt(messages: Any) -> str:
    lines: list[str] = []
    for message in _list(messages):
        if not isinstance(message, Mapping):
            continue
        role = _clean(message.get("role") or "message")
        content = _content_text(message.get("content"))
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _responses_input_prompt(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        message_prompt = _messages_prompt(value)
        if message_prompt:
            return message_prompt
        parts = [_content_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return _content_text(value)


def _provider_options(payload: Mapping[str, Any]) -> dict[str, Any]:
    options = _dict(payload.get("norman"))
    if not options:
        metadata = _dict(payload.get("metadata"))
        options = _dict(metadata.get("norman"))
    return options


def _provider_runtime(provider: str) -> str:
    clean = _lower(provider).replace("_", "-")
    if clean in {"openai", "openai-chat-completions", "openai-responses"}:
        return "openai"
    if clean in {"bedrock", "aws-bedrock"}:
        return "bedrock"
    if clean in _LOCAL_RUNTIMES:
        return "localllm"
    return "auto"


def _adapter_mode(value: Any) -> str:
    clean = _lower(value).replace("-", "_").replace(" ", "_")
    clean = _ADAPTER_MODE_ALIASES.get(clean, clean)
    return clean if clean in _ADAPTER_MODES else "route_only"


def classify_prompt(
    prompt: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify the prompt before any model is allowed to consume it."""

    clean = _clean(prompt)
    lowered = clean.lower()
    tokens = set(_word_tokens(clean))
    key_terms = tui_route_intent.classify_key_terms(clean)
    button_intent = str(key_terms.get("button_intent") or "")
    artifacts = [dict(item) for item in artifacts or [] if isinstance(item, Mapping)]
    artifact_kind = _artifact_task_kind(artifacts)

    intent = "general_prompt"
    task_kind = artifact_kind or NorllamaTaskKind.PLAN.value
    intent_confidence = 0.55
    reasons: list[str] = []

    if artifact_kind:
        intent = f"{artifact_kind}_artifact"
        task_kind = artifact_kind
        intent_confidence = 0.92
        reasons.append("artifact type selects specialist lane")
    elif button_intent == "copy_response":
        intent = "copy_response"
        task_kind = NorllamaTaskKind.SUMMARIZE.value
        intent_confidence = 0.95
        reasons.append("reply control button: copy")
    elif button_intent == "simplify_response":
        intent = "simplify_response"
        task_kind = NorllamaTaskKind.SUMMARIZE.value
        intent_confidence = 0.9
        reasons.append("reply control button: simpler")
    elif button_intent == "verify_response":
        intent = "verify_or_audit"
        task_kind = NorllamaTaskKind.VERIFY.value
        intent_confidence = 0.88
        reasons.append("reply control button: verify")
    elif button_intent == "dig_deeper":
        intent = "deep_dive"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.88
        reasons.append("reply control button: dig deeper")
    elif button_intent == "handoff_or_relay":
        intent = "handoff_or_relay"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.88
        reasons.append("reply control button: handoff/relay")
    elif _quick_status(lowered):
        intent = "quick_status"
        task_kind = NorllamaTaskKind.SUMMARIZE.value
        intent_confidence = 0.94
        reasons.append("short status/update prompt")
    elif _contains_any(lowered, _NEXT_PHRASES):
        intent = "next_steps"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.9
        reasons.append("operator asks for next step")
    elif _contains_any(lowered, _CONTINUE_PHRASES):
        intent = "continue_work"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.9
        reasons.append("operator continuation prompt")
    elif _contains_any(lowered, _RETRY_PHRASES):
        intent = "retry_last_step"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.88
        reasons.append("operator asks to retry the previous step")
    elif _contains_any(lowered, _STOP_PHRASES):
        intent = "stop_or_pause"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.88
        reasons.append("operator asks to stop or pause current work")
    elif _contains_any(lowered, _UNDO_PHRASES):
        intent = "undo_or_rollback"
        task_kind = NorllamaTaskKind.VERIFY.value
        intent_confidence = 0.86
        reasons.append("operator asks to undo or rollback state")
    elif _contains_any(lowered, _RESTART_PHRASES):
        intent = "restart_or_recover"
        task_kind = NorllamaTaskKind.VERIFY.value
        intent_confidence = 0.86
        reasons.append("operator asks to restart or recover a service")
    elif _contains_any(lowered, _SHIP_PHRASES):
        intent = "ship_or_release"
        task_kind = NorllamaTaskKind.VERIFY.value
        intent_confidence = 0.86
        reasons.append("operator asks to ship or release")
    elif "rerank" in tokens or "rank" in tokens or "sort" in tokens:
        intent = "rerank_or_filter"
        task_kind = NorllamaTaskKind.RERANK.value
        intent_confidence = 0.82
        reasons.append("ranking/filtering prompt")
    elif _contains_any(lowered, _WEB_RESEARCH_WORDS):
        intent = "research_or_scout"
        task_kind = NorllamaTaskKind.SCOUT.value
        intent_confidence = 0.78
        reasons.append("web/search/research signal")
    elif tokens & _VERIFY_WORDS:
        intent = "verify_or_audit"
        task_kind = NorllamaTaskKind.VERIFY.value
        intent_confidence = 0.76
        reasons.append("verification/audit signal")
    elif tokens & _CODE_WORDS:
        intent = "code_or_patch"
        task_kind = NorllamaTaskKind.CODE.value
        intent_confidence = 0.76
        reasons.append("code/repo signal")
    elif tui_route_intent.is_broad_planning(lowered):
        intent = "planning_or_architecture"
        task_kind = NorllamaTaskKind.PLAN.value
        intent_confidence = 0.86
        reasons.append("broad architecture/planning prompt")
    elif "summarize" in tokens or "summary" in tokens:
        intent = "summarize"
        task_kind = NorllamaTaskKind.SUMMARIZE.value
        intent_confidence = 0.8
        reasons.append("summarization signal")

    destructive = any(re.search(pattern, lowered) for pattern in _DESTRUCTIVE_PATTERNS)
    external_mutation = _contains_any(lowered, _EXTERNAL_MUTATION_WORDS)
    local_mutation = bool(tokens & _LOCAL_MUTATION_WORDS)
    secret_sensitive = bool(tokens & _SECRET_WORDS)
    if destructive:
        risk_class = "destructive"
        risk_level = "critical"
    elif external_mutation or intent in {"restart_or_recover", "ship_or_release"}:
        risk_class = "external_mutation"
        risk_level = "high"
    elif local_mutation or intent == "undo_or_rollback":
        risk_class = "local_mutation"
        risk_level = "medium"
    elif secret_sensitive:
        risk_class = "secret_sensitive"
        risk_level = "medium"
    else:
        risk_class = "read_only"
        risk_level = "low"

    requires_approval = risk_level in {"high", "critical"} or intent in {
        "undo_or_rollback"
    }
    cloud_escalation_candidate = risk_level in {"high", "critical"} or intent in {
        "research_or_scout",
        "verify_or_audit",
    }

    return {
        "schema": "norman.prompt-intent.v1",
        "intent": intent,
        "intent_confidence": intent_confidence,
        "task_kind": task_kind,
        "risk_class": risk_class,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "read_only": risk_class == "read_only",
        "requires_tools": risk_class
        in {"destructive", "external_mutation", "local_mutation"}
        or intent in {"code_or_patch", "research_or_scout"},
        "external_side_effects_possible": risk_class
        in {"destructive", "external_mutation"},
        "cloud_escalation_candidate": cloud_escalation_candidate,
        "reasons": reasons or ["fallback prompt classification"],
        "signals": {
            "status": _has_status_signal(lowered),
            "button_intent": button_intent,
            "web_research": intent == "research_or_scout",
            "code": intent == "code_or_patch",
            "mutation": risk_class != "read_only",
            "secret_sensitive": secret_sensitive,
        },
    }


def _reasoning_profile(
    classification: Mapping[str, Any],
    *,
    prompt: str,
) -> dict[str, Any]:
    tokens = set(_word_tokens(prompt))
    intent = _clean(classification.get("intent"))
    task_kind = _clean(classification.get("task_kind"))
    risk_level = _clean(classification.get("risk_level"))
    word_count = len(_word_tokens(prompt))
    high_reasoning_signals = sorted(tokens & _HIGH_REASONING_WORDS)
    if intent in _DETERMINISTIC_INTENTS and risk_level == "low":
        tier = "simple"
        effort = "deterministic_or_tiny_local"
        reason = "prompt matches a short operator-control/status intent"
    elif intent in {"deep_dive", "planning_or_architecture"}:
        tier = "high_reasoning"
        effort = "spark_high_reasoning"
        reason = "prompt asks for deeper reasoning, architecture, routing, or planning"
    elif task_kind in _SPECIALIST_TASK_KINDS:
        tier = "specialist"
        effort = "local_specialist"
        reason = "prompt or artifacts select a specialist lane"
    elif risk_level in {"high", "critical"}:
        tier = "high_reasoning"
        effort = "local_high_reasoning_then_approval"
        reason = "prompt may mutate external state or needs approval"
    elif (
        high_reasoning_signals
        or word_count >= 80
        or task_kind
        in {
            NorllamaTaskKind.CODE.value,
            NorllamaTaskKind.VERIFY.value,
            NorllamaTaskKind.JUDGE.value,
        }
    ):
        tier = "high_reasoning"
        effort = "spark_high_reasoning"
        reason = "prompt needs planning, verification, code, or policy reasoning"
    else:
        tier = "standard_local_llm"
        effort = "spark_local_llm"
        reason = "prompt is local-eligible and needs normal language reasoning"
    return {
        "schema": "norman.prompt-reasoning-profile.v1",
        "tier": tier,
        "effort": effort,
        "word_count": word_count,
        "high_reasoning_signals": high_reasoning_signals,
        "reason": reason,
    }


def _strategy_for_prompt(
    classification: Mapping[str, Any],
    reasoning: Mapping[str, Any],
    *,
    allow_cloud_escalation: bool,
) -> dict[str, Any]:
    tier = _clean(reasoning.get("tier"))
    intent = _clean(classification.get("intent"))
    task_kind = _clean(classification.get("task_kind"))
    risk_level = _clean(classification.get("risk_level"))
    if tier == "simple":
        strategy = "simple_local"
        primary = "deterministic_prompt_gate"
        fallback = "norllama_tiny_or_status_summarizer"
    elif tier == "specialist":
        strategy = "local_specialist"
        primary = f"norllama_{task_kind}"
        fallback = "spark_local_llm"
    elif tier == "high_reasoning":
        strategy = "local_high_reasoning"
        primary = "spark_high_reasoning_local"
        fallback = "cloud_llm_receipted_tiebreaker"
    else:
        strategy = "standard_local_llm"
        primary = "spark_local_llm"
        fallback = "spark_high_reasoning_local"
    if intent == "research_or_scout":
        fallback = "web_search_or_perplexity_then_local_synthesis"
    cloud_position = (
        "disabled"
        if not allow_cloud_escalation
        else "last_resort_after_local_receipt"
        if risk_level in {"high", "critical"} or strategy == "local_high_reasoning"
        else "tie_breaker_only"
    )
    return {
        "schema": "norman.prompt-routing-strategy.v1",
        "strategy": strategy,
        "primary_executor": primary,
        "fallback_executor": fallback,
        "cloud_position": cloud_position,
        "cloud_requires_receipt": True,
        "local_prefilter_required": True,
        "autosense_local_runtime": True,
        "proxy_safe": True,
        "client_integration_mode": "provider_adapter_or_sdk_wrapper",
        "ordered_cascade": [
            "deterministic_prompt_gate",
            "local_specialists_if_applicable",
            "spark_local_llm",
            "spark_high_reasoning_local",
            "web_search_if_task_requires_fresh_external_data",
            "cloud_llm_receipted_tiebreaker",
        ],
    }


def _runtime_provider(requested_runtime: str) -> str:
    runtime = _lower(requested_runtime).replace("_", "-")
    if runtime in _CLOUD_RUNTIMES:
        return "aws-bedrock" if runtime == "bedrock" else runtime
    if runtime in _LOCAL_RUNTIMES:
        return "norllama"
    return ""


def _route_policy_for_prompt(
    *,
    base_policy: Mapping[str, Any] | None,
    classification: Mapping[str, Any],
    requested_runtime: str,
    requested_model: str,
    force_requested_runtime: bool,
    allow_cloud_escalation: bool,
) -> dict[str, Any]:
    incoming = dict(base_policy or {})
    forced_provider = (
        _runtime_provider(requested_runtime) if force_requested_runtime else ""
    )
    if forced_provider:
        incoming["provider"] = forced_provider
        incoming["preferred_provider"] = forced_provider
        if forced_provider in _CLOUD_RUNTIMES:
            incoming["allow_cloud_proxy"] = bool(allow_cloud_escalation)
        if requested_model:
            incoming["model"] = requested_model
            incoming["route_lock"] = True
    else:
        incoming.pop("model", None)
        incoming.pop("route_lock", None)

    incoming.setdefault("provider", "norllama")
    incoming.setdefault("preferred_provider", "norllama")
    incoming.setdefault("local_first", True)
    incoming.setdefault("use_capability_catalog", True)
    incoming.setdefault("model_selection", "warm_policy")
    incoming.setdefault("allow_cloud_proxy", False)
    incoming.setdefault("allow_cloud_tool_proxy", False)
    incoming["prompt_load_balancer"] = True
    incoming["prompt_intent"] = classification.get("intent")
    incoming["prompt_risk_level"] = classification.get("risk_level")
    incoming["prompt_risk_class"] = classification.get("risk_class")
    incoming["cloud_escalation_allowed_by_prompt_router"] = bool(allow_cloud_escalation)
    _, _, with_local_first_catalog_defaults = _console_runtime_policy_helpers()
    return with_local_first_catalog_defaults(incoming)


def balance_prompt(
    *,
    prompt: str,
    source: str = "",
    session: str = "",
    requested_runtime: str = "auto",
    requested_model: str = "",
    force_requested_runtime: bool = False,
    allow_cloud_escalation: bool = True,
    route_policy: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_prompt = _clean(prompt)
    if not clean_prompt:
        raise ValueError("prompt is required")

    prompt_route_id = f"prompt_route_{uuid.uuid4().hex}"
    classification = classify_prompt(clean_prompt, artifacts=artifacts)
    stateful_control = _stateful_terse_control(
        classification=classification,
        context=context,
    )
    if stateful_control["applies"]:
        classification = dict(classification)
        classification["stateful_control"] = stateful_control
        if stateful_control["requires_approval"]:
            classification["requires_approval"] = True
        if not stateful_control["execution_allowed"]:
            classification["risk_level"] = (
                "high"
                if stateful_control["requires_approval"]
                else classification.get("risk_level", "medium")
            )
            classification["reasons"] = [
                *list(classification.get("reasons") or []),
                *stateful_control["blockers"],
            ]
    reasoning = _reasoning_profile(classification, prompt=clean_prompt)
    orchestration_plan = plan_reasoning_turn(
        prompt=clean_prompt,
        classification=classification,
        context=context,
        artifacts=[dict(item) for item in artifacts or [] if isinstance(item, Mapping)],
        source=source,
        session=session,
    )
    reasoning_receipt = build_reasoning_receipt(orchestration_plan)
    strategy = _strategy_for_prompt(
        classification,
        reasoning,
        allow_cloud_escalation=allow_cloud_escalation,
    )
    policy = _route_policy_for_prompt(
        base_policy=route_policy,
        classification=classification,
        requested_runtime=requested_runtime,
        requested_model=requested_model,
        force_requested_runtime=force_requested_runtime,
        allow_cloud_escalation=allow_cloud_escalation,
    )
    task_kind = classification["task_kind"]
    task_request = NorllamaTaskRequest(
        kind=task_kind,
        input_text=clean_prompt,
        route_policy=policy,
        artifacts=[dict(item) for item in artifacts or [] if isinstance(item, Mapping)],
        metadata={
            "prompt_route_id": prompt_route_id,
            "source": source,
            "session": session,
            "phase": "prompt_balance",
            "execution_mode": "prompt_load_balancer",
            "requested_runtime": requested_runtime,
            "requested_model": requested_model,
            "force_requested_runtime": force_requested_runtime,
        },
        task_id=prompt_route_id,
    )
    route = route_task(task_request)
    resolve_runtime_mode, route_decision, _ = _console_runtime_policy_helpers()
    runtime_state = resolve_runtime_mode(policy)
    decision = route_decision(
        task_kind=task_kind,
        route=route,
        policy_state=runtime_state,
        runner="norllama",
        fallback_order=["norllama", "local_tool", "web_search", "cloud_llm"],
        metadata={
            "route_policy": policy,
            "prompt_intent": classification,
            "source": source,
            "session": session,
            "context": dict(context or {}),
        },
    )
    receipt = build_task_receipt(
        task_request,
        route,
        status="planned",
        output={
            "adapter_required": True,
            "summary": "prompt route decision only; no model execution performed",
            "target_model": route.model,
            "route_selected_model": route.model,
            "requested_model": route.model,
            "effective_runtime_model": route.model,
        },
        metadata={
            "phase": "prompt_balance",
            "execution_mode": "prompt_load_balancer",
            "completion_requested": False,
        },
    ).as_dict()

    local_first = bool(route.local and not route.cloud_proxy and decision.allowed)
    cloud_llm_allowed = bool(runtime_state.cloud_llm_allowed and allow_cloud_escalation)
    requires_approval = bool(classification["requires_approval"])
    if stateful_control["applies"]:
        requires_approval = bool(stateful_control["requires_approval"])
    execution_allowed = bool(decision.allowed and not requires_approval)
    if stateful_control["applies"] and not stateful_control["execution_allowed"]:
        execution_allowed = False
    cloud_escalation_reason = ""
    if classification["cloud_escalation_candidate"]:
        cloud_escalation_reason = "eligible only after local preflight, risk classification, and receipt proof"

    return {
        "schema": PROMPT_LOAD_BALANCER_SCHEMA,
        "prompt_route_id": prompt_route_id,
        "mode": "prompt_load_balancer",
        "source": source,
        "session": session,
        "classification": classification,
        "stateful_control": stateful_control,
        "reasoning_profile": reasoning,
        "reasoning_orchestration": orchestration_plan,
        "routing_strategy": strategy,
        "prompt_preprocessor": {
            "schema": "norman.prompt-preprocessor.v1",
            "stages": [
                {
                    "name": "deterministic_prompt_intent",
                    "status": "pass",
                    "local": True,
                },
                {
                    "name": "norllama_intent_classifier",
                    "status": "available_via_policy",
                    "local": True,
                    "route": route.lane,
                },
                {
                    "name": "network_local_runtime_autosense",
                    "status": "handled_by_norllama_policy",
                    "local": True,
                    "route": route.provider,
                },
            ],
            "normalization": "trim_lower_token_fuzzy_intent",
        },
        "route": route.as_dict(),
        "decision": decision.as_dict(),
        "recommendation": {
            "schema": "norman.prompt-load-balancer.recommendation.v1",
            "selected_runtime": "localllm" if route.local else route.provider,
            "selected_provider": route.provider,
            "selected_model": route.model,
            "selected_lane": route.lane,
            "task_kind": task_kind,
            "reasoning_tier": reasoning["tier"],
            "routing_strategy": strategy["strategy"],
            "primary_executor": strategy["primary_executor"],
            "fallback_executor": strategy["fallback_executor"],
            "local_first": local_first,
            "cloud_last_resort": True,
            "cloud_llm_allowed_by_mode": runtime_state.cloud_llm_allowed,
            "cloud_escalation_allowed": cloud_llm_allowed,
            "cloud_escalation_candidate": classification["cloud_escalation_candidate"],
            "cloud_escalation_reason": cloud_escalation_reason,
            "requires_approval": requires_approval,
            "execution_allowed": execution_allowed,
            "external_side_effects_possible": classification[
                "external_side_effects_possible"
            ],
            "selected_action": stateful_control["selected_action"],
            "execution_permission": stateful_control["execution_permission"],
            "approval_binding": stateful_control["approval_binding"],
            "target_identity": stateful_control["target_identity"],
            "tool_selection": stateful_control["tool_selection"],
            "control_route": stateful_control["route"],
            "visible_response": stateful_control["visible_response"],
            "stateful_blockers": stateful_control["blockers"],
            "next_hop": "console_runtime_kernel"
            if execution_allowed
            else "local_preflight_or_approval",
            "escalation_order": [
                *strategy["ordered_cascade"],
            ],
            "selected_skill_ids": orchestration_plan["selected_skill_ids"],
            "max_tool_iterations": orchestration_plan["tool_plan"][
                "max_tool_iterations"
            ],
            "continuous_tool_use": orchestration_plan["tool_plan"][
                "continuous_tool_use"
            ],
            "verification_tools": orchestration_plan["tool_plan"]["verification_tools"],
        },
        "route_receipt_preview": {
            "schema": PROMPT_ROUTE_RECEIPT_SCHEMA,
            "execution_performed": False,
            "norllama_route_receipt": receipt.get("route_receipt", {}),
            "reasoning_receipt": reasoning_receipt,
        },
    }


def provider_adapter_decision(
    *,
    provider: str,
    endpoint: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    provider_payload = dict(payload)
    options = _provider_options(provider_payload)
    adapter_mode = _adapter_mode(
        options.get("adapter_mode")
        or options.get("intermediary_mode")
        or options.get("mode")
    )
    mode_policy = _ADAPTER_MODES[adapter_mode]
    prompt = ""
    if endpoint == "openai.chat.completions":
        prompt = _messages_prompt(provider_payload.get("messages"))
    elif endpoint == "openai.responses":
        prompt = _responses_input_prompt(provider_payload.get("input"))
    else:
        prompt = _responses_input_prompt(
            provider_payload.get("input")
            or provider_payload.get("prompt")
            or provider_payload.get("messages")
        )
    if not prompt:
        raise ValueError("provider request does not contain prompt text")

    force_requested_runtime = _flag(options.get("force_requested_runtime"), False)
    requested_runtime = _clean(options.get("requested_runtime")) or _provider_runtime(
        provider
    )
    requested_model = _clean(options.get("requested_model")) or _clean(
        provider_payload.get("model")
    )
    caller_route_policy = _dict(options.get("route_policy"))
    route_policy: dict[str, Any] = {}
    route_policy["provider_adapter"] = True
    route_policy["provider_adapter_provider"] = provider
    route_policy["provider_adapter_endpoint"] = endpoint
    route_policy["provider_adapter_mode"] = adapter_mode
    route_policy["caller_requested_model"] = requested_model
    route_policy["caller_route_policy_supplied"] = bool(caller_route_policy)
    route_policy["caller_route_policy_trusted"] = False
    route_policy["intermediary_mode"] = adapter_mode
    route_policy["intermediary_enforcement_level"] = mode_policy["enforcement_level"]
    allow_cloud = _flag(options.get("allow_cloud_escalation"), True)
    if adapter_mode == "strict_local":
        allow_cloud = False
    decision = balance_prompt(
        prompt=prompt,
        source=_clean(options.get("source")) or _clean(provider),
        session=_clean(options.get("session")),
        requested_runtime=requested_runtime,
        requested_model=requested_model,
        force_requested_runtime=force_requested_runtime,
        allow_cloud_escalation=allow_cloud,
        route_policy=route_policy,
        context={
            "provider_adapter": {
                "provider": provider,
                "endpoint": endpoint,
                "request_model": provider_payload.get("model"),
                "stream": bool(provider_payload.get("stream")),
                "adapter_mode": adapter_mode,
            }
        },
        artifacts=[dict(item) for item in _list(options.get("artifacts"))],
    )
    return {
        "schema": PROMPT_PROVIDER_ADAPTER_SCHEMA,
        "mode": "provider_adapter",
        "provider": provider,
        "endpoint": endpoint,
        "adapter_mode": adapter_mode,
        "adapter_mode_policy": {
            "schema": "norman.prompt-provider-adapter.mode-policy.v1",
            "label": mode_policy["label"],
            "enforcement_level": mode_policy["enforcement_level"],
            "mutates_request": mode_policy["mutates_request"],
            "blocks_request": mode_policy["blocks_request"],
            "uses_local_intelligence": mode_policy["uses_local_intelligence"],
            "cloud_allowed": allow_cloud,
        },
        "execution_performed": False,
        "forwarding_performed": False,
        "proxy_safe": True,
        "transparent_mitm": False,
        "normalized_prompt": prompt,
        "caller_request": {
            "model": provider_payload.get("model"),
            "stream": bool(provider_payload.get("stream")),
            "has_messages": bool(provider_payload.get("messages")),
            "has_input": provider_payload.get("input") is not None,
            "route_policy_supplied": bool(caller_route_policy),
            "route_policy_trusted": False,
        },
        "norman_route": decision,
        "next_hop": decision["recommendation"]["next_hop"],
        "selected_runtime": decision["recommendation"]["selected_runtime"],
        "selected_model": decision["recommendation"]["selected_model"],
        "selected_provider": decision["recommendation"]["selected_provider"],
        "cloud_position": decision["routing_strategy"]["cloud_position"],
        "cloud_requires_receipt": True,
        "advisory_only": adapter_mode in {"transparent_log_only", "shadow_compare"},
        "integration_contract": {
            "schema": "norman.prompt-provider-adapter.contract.v1",
            "client_action": mode_policy["client_action"],
            "openai_compatible_response": False,
            "route_receipt_required_before_cloud": True,
            "local_runtime_autosense": True,
            "transparent_network_interception": False,
        },
    }


def prompt_load_balancer_capabilities() -> dict[str, Any]:
    skill_registry = build_skill_registry()
    background_loop = kpi_background_loop_plan()
    return {
        "schema": "norman.prompt-load-balancer.capabilities.v1",
        "mode": "prompt_load_balancer",
        "available": True,
        "execution_performed": False,
        "supports": {
            "deterministic_prefilter": True,
            "reasoning_tier_selection": True,
            "local_first": True,
            "cloud_last_resort": True,
            "policy_authority": True,
            "route_receipt_preview": True,
            "cross_tui_client": True,
            "provider_adapter_mode": True,
            "sdk_wrapper_mode": True,
            "transparent_mitm_required": False,
            "local_runtime_autosense": True,
            "openai_chat_completions_adapter": True,
            "openai_responses_adapter": True,
            "reasoning_orchestration": True,
            "skill_registry": True,
            "kpi_background_skills": True,
            "continuous_tool_use_plan": True,
            "tool_required_verification": True,
        },
        "intermediary_modes": [
            {
                "mode": mode,
                **policy,
                "transparent_network_interception": False,
            }
            for mode, policy in _ADAPTER_MODES.items()
        ],
        "integration_modes": [
            {
                "mode": "advisory",
                "description": "Client asks Norman for a decision, then executes the selected route.",
            },
            {
                "mode": "provider_adapter",
                "description": "Client sends provider-shaped requests to Norman; Norman applies policy before forwarding or rerouting.",
            },
            {
                "mode": "sdk_wrapper",
                "description": "Client library wraps Bedrock/OpenAI/Ollama calls with Norman route decisions.",
            },
        ],
        "reasoning_tiers": [
            "simple",
            "specialist",
            "standard_local_llm",
            "high_reasoning",
        ],
        "quick_intents": [
            "quick_status",
            "next_steps",
            "continue_work",
            "retry_last_step",
            "stop_or_pause",
            "undo_or_rollback",
            "restart_or_recover",
            "ship_or_release",
            "summarize",
            "verify_or_audit",
            "code_or_patch",
            "research_or_scout",
            "rerank_or_filter",
        ],
        "risk_classes": [
            "read_only",
            "secret_sensitive",
            "local_mutation",
            "external_mutation",
            "destructive",
        ],
        "escalation_order": [
            "deterministic_prompt_gate",
            "local_specialists_if_applicable",
            "spark_local_llm",
            "spark_high_reasoning_local",
            "web_search_if_task_requires_fresh_external_data",
            "cloud_llm_receipted_tiebreaker",
        ],
        "skill_registry": {
            "schema": skill_registry["schema"],
            "version": skill_registry["version"],
            "skill_count": skill_registry["skill_count"],
            "skill_ids": [skill["skill_id"] for skill in skill_registry["skills"]],
        },
        "kpi_background_loop": {
            "schema": background_loop["schema"],
            "registry_version": background_loop["registry_version"],
            "candidate_count": background_loop["candidate_count"],
            "cloud_allowed": background_loop["loop_policy"]["cloud_allowed"],
        },
    }
