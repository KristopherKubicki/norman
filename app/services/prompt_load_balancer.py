from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from typing import Any, Mapping

from app.services.console_runtime.policy import (
    resolve_runtime_mode,
    route_decision,
    with_local_first_catalog_defaults,
)
from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.types import NorllamaTaskKind, NorllamaTaskRequest

PROMPT_LOAD_BALANCER_SCHEMA = "norman.prompt-load-balancer.v1"
PROMPT_ROUTE_RECEIPT_SCHEMA = "norman.prompt-load-balancer.receipt.v1"

_TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "force"}
_CLOUD_RUNTIMES = {"aws-bedrock", "bedrock", "codex", "openai", "openai-direct"}
_LOCAL_RUNTIMES = {"local", "localllm", "norllama", "ollama", "openai-compatible"}
_STATUS_WORDS = {
    "health",
    "progress",
    "state",
    "status",
    "stauts",
    "stats",
    "stuats",
    "sutats",
    "update",
    "updates",
}
_FILLER_WORDS = {
    "a",
    "about",
    "any",
    "are",
    "can",
    "could",
    "do",
    "give",
    "got",
    "have",
    "hey",
    "how",
    "hows",
    "i",
    "is",
    "it",
    "just",
    "me",
    "on",
    "please",
    "pls",
    "quick",
    "quickly",
    "the",
    "there",
    "this",
    "we",
    "what",
    "whats",
    "where",
    "you",
}
_CONTINUE_PHRASES = (
    "go ahead",
    "keep going",
    "keep working",
    "proceed",
    "do it",
    "lets go",
    "let's go",
)
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
    "write",
}
_SECRET_WORDS = {"credential", "key", "password", "secret", "token"}


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


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, Mapping) else {}


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower())


def _contains_any(text: str, needles: set[str] | tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _looks_like_status_word(token: str) -> bool:
    if token in _STATUS_WORDS:
        return True
    return any(
        SequenceMatcher(None, token, word).ratio() >= 0.8 for word in _STATUS_WORDS
    )


def _has_status_signal(text: str) -> bool:
    tokens = _word_tokens(text)
    if any(_looks_like_status_word(token) for token in tokens):
        return True
    return any(
        phrase in text
        for phrase in (
            "how are things",
            "how is it going",
            "how's it going",
            "where are we",
            "where do we stand",
        )
    )


def _quick_status(text: str) -> bool:
    tokens = _word_tokens(text)
    meaningful = [token for token in tokens if token not in _FILLER_WORDS]
    return _has_status_signal(text) and len(meaningful) <= 8


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


def classify_prompt(
    prompt: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify the prompt before any model is allowed to consume it."""

    clean = _clean(prompt)
    lowered = clean.lower()
    tokens = set(_word_tokens(clean))
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
    elif external_mutation:
        risk_class = "external_mutation"
        risk_level = "high"
    elif local_mutation:
        risk_class = "local_mutation"
        risk_level = "medium"
    elif secret_sensitive:
        risk_class = "secret_sensitive"
        risk_level = "medium"
    else:
        risk_class = "read_only"
        risk_level = "low"

    requires_approval = risk_level in {"high", "critical"}
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
            "web_research": intent == "research_or_scout",
            "code": intent == "code_or_patch",
            "mutation": risk_class != "read_only",
            "secret_sensitive": secret_sensitive,
        },
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
    execution_allowed = bool(decision.allowed and not requires_approval)
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
            "next_hop": "console_runtime_kernel"
            if execution_allowed
            else "local_preflight_or_approval",
            "escalation_order": [
                "deterministic_prompt_gate",
                "norllama_specialists",
                "norllama_local_llm",
                "web_search_if_needed",
                "cloud_llm_only_with_policy_receipt",
            ],
        },
        "route_receipt_preview": {
            "schema": PROMPT_ROUTE_RECEIPT_SCHEMA,
            "execution_performed": False,
            "norllama_route_receipt": receipt.get("route_receipt", {}),
        },
    }


def prompt_load_balancer_capabilities() -> dict[str, Any]:
    return {
        "schema": "norman.prompt-load-balancer.capabilities.v1",
        "mode": "prompt_load_balancer",
        "available": True,
        "execution_performed": False,
        "supports": {
            "deterministic_prefilter": True,
            "local_first": True,
            "cloud_last_resort": True,
            "policy_authority": True,
            "route_receipt_preview": True,
            "cross_tui_client": True,
        },
        "quick_intents": [
            "quick_status",
            "next_steps",
            "continue_work",
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
            "norllama_specialists",
            "norllama_local_llm",
            "web_search_if_needed",
            "cloud_llm_only_with_policy_receipt",
        ],
    }
