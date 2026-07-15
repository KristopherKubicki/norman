from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

STATUS_WORDS = {
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

STATUS_FILLER_WORDS = {
    "a",
    "about",
    "an",
    "any",
    "are",
    "brief",
    "can",
    "could",
    "current",
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
    "session",
    "system",
    "that",
    "the",
    "there",
    "things",
    "this",
    "tui",
    "tuis",
    "us",
    "we",
    "what",
    "whats",
    "where",
    "you",
}

BROAD_PLANNING_MARKERS = (
    "/fork",
    "architecture",
    "autonomous",
    "autonomously",
    "clone a tui",
    "clone tui",
    "control plane",
    "fork a tui",
    "fork tui",
    "forking tui",
    "how do we",
    "how should",
    "multiple sessions",
    "proposal",
    "propose",
    "roadmap",
    "same tui",
    "strategy",
    "subagent",
    "subagents",
)

BROAD_PLANNING_CONFIRM_MARKERS = (
    "architecture",
    "autonomous",
    "autonomously",
    "clone",
    "control plane",
    "different tasks",
    "fork",
    "many sessions",
    "multiple sessions",
    "roadmap",
    "same tui",
    "subagent",
    "subagents",
)

PROCEED_PHRASES = (
    "what's next",
    "whats next",
    "what next",
    "wahts next",
    "proceed",
    "continue",
    "resume",
    "go ahead",
    "do it",
    "make it so",
    "keep going",
)

RETRY_PHRASES = ("retry", "try again", "rerun", "run it again", "again")
STOP_PHRASES = ("stop", "pause", "halt", "cancel")
UNDO_PHRASES = ("undo", "go back", "rollback", "roll back", "revert")
RESTART_PHRASES = ("restart", "recover")
SHIP_PHRASES = ("ship it", "ship", "release it")
BENCHMARK_PHRASES = ("benchmark", "hybrid", "optimizer", "metric", "test")
DIG_PHRASES = ("dig", "dig in", "dig into", "deep dive", "go deeper", "look deeper")
SIMPLER_PHRASES = (
    "simpler",
    "simplify",
    "make simpler",
    "make it simpler",
    "plain english",
    "eli5",
)
VERIFY_PHRASES = ("verify", "check this", "validate", "audit this", "double check")
COPY_PHRASES = ("copy", "copy this", "copy response", "copy text")
HANDOFF_PHRASES = (
    "handoff",
    "hand off",
    "relay",
    "send to",
    "pass to",
    "ask scout",
    "ask uplink",
    "ask cloudagent",
    "ask housebot",
)

ROUTE_STATUS_SUBJECTS = (
    " bedrock",
    " cloud",
    " cloud token",
    " codex",
    " configured",
    " configuration",
    " fallback",
    " failover",
    " gpt-",
    " llm.home.arpa",
    " local model",
    " local token",
    " localllm",
    " model",
    " norllama",
    " openai",
    " preflight",
    " route",
    " routed",
    " routing",
    " runtime",
    " session",
    " spark",
    " tui",
    " tuis",
    " usage",
)


def clean_prompt(value: Any) -> str:
    return str(value or "").strip()


def word_tokens(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9._-]*", clean_prompt(value).lower())


def padded_lower(value: Any) -> str:
    return f" {clean_prompt(value).lower()} "


def contains_any(text: str, needles: set[str] | tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def looks_like_status_word(token: str) -> bool:
    if token in STATUS_WORDS:
        return True
    return any(
        SequenceMatcher(None, token, word).ratio() >= 0.8 for word in STATUS_WORDS
    )


def has_status_signal(value: Any) -> bool:
    text = clean_prompt(value).lower()
    tokens = word_tokens(text)
    if any(looks_like_status_word(token) for token in tokens):
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


def is_broad_planning(value: Any) -> bool:
    lower = clean_prompt(value).lower()
    if not lower:
        return False
    if not contains_any(lower, BROAD_PLANNING_MARKERS):
        return False
    return contains_any(lower, BROAD_PLANNING_CONFIRM_MARKERS)


def is_quick_status(value: Any) -> bool:
    if is_broad_planning(value):
        return False
    tokens = word_tokens(value)
    if not any(looks_like_status_word(token) for token in tokens):
        return False
    meaningful = [token for token in tokens if token not in STATUS_FILLER_WORDS]
    return bool(has_status_signal(value) and len(meaningful) <= 8)


def is_route_status_diagnostic(value: Any) -> bool:
    if is_broad_planning(value):
        return False
    prompt = clean_prompt(value)
    lower = padded_lower(prompt)
    route_subject = contains_any(lower, ROUTE_STATUS_SUBJECTS) or re.search(
        r"\b(?:tokens?|cost|spend)\b", lower
    )
    if not route_subject:
        return False
    asks_status = bool(
        "?" in prompt
        or re.search(
            r"\b(?:are|can|could|did|does|do|how|is|should|was|were|what|which|why)\b",
            lower,
        )
        or contains_any(
            lower,
            (
                " status",
                " check status",
                " check on",
                " configured right",
                " not configured right",
                " wrong model",
                " wrong runtime",
            ),
        )
    )
    if not asks_status:
        return False
    mutating_order = re.search(
        r"\b(?:apply|change|commit|deploy|edit|fix|implement|install|patch|push|restart|run|sync|update)\b",
        lower,
    )
    diagnostic_intro = re.search(
        r"\b(?:why|what|which|how|did|does|do|is|are|was|were|can|could|should)\b",
        lower,
    )
    if mutating_order and not diagnostic_intro:
        return False
    return not re.search(
        r"\b(?:go ahead|proceed|do it|make it|please)\b"
        r".{0,80}\b(?:deploy|fix|implement|install|patch|push|restart|run|sync|update)\b",
        lower,
    )


def requested_action(value: Any) -> str:
    lower = clean_prompt(value).lower()
    if is_route_status_diagnostic(lower) or is_quick_status(lower):
        return "status"
    if any(token in lower for token in ("status", "check on", "wedged", "crashing")):
        return "status"
    if contains_any(lower, COPY_PHRASES):
        return "copy_response"
    if contains_any(lower, SIMPLER_PHRASES):
        return "simplify_response"
    if contains_any(lower, VERIFY_PHRASES):
        return "verify_response"
    if contains_any(lower, DIG_PHRASES):
        return "dig_deeper"
    if contains_any(lower, HANDOFF_PHRASES):
        return "handoff_or_relay"
    if contains_any(lower, PROCEED_PHRASES):
        return "proceed_or_next"
    if contains_any(lower, UNDO_PHRASES):
        return "undo_or_back"
    if contains_any(lower, BENCHMARK_PHRASES):
        return "benchmark_or_optimizer"
    return "operator_prompt"


def button_intent(value: Any) -> str:
    lower = clean_prompt(value).lower()
    if is_route_status_diagnostic(lower) or is_quick_status(lower):
        return "status"
    if contains_any(lower, COPY_PHRASES):
        return "copy_response"
    if contains_any(lower, SIMPLER_PHRASES):
        return "simplify_response"
    if contains_any(lower, VERIFY_PHRASES):
        return "verify_response"
    if contains_any(lower, DIG_PHRASES):
        return "dig_deeper"
    if contains_any(lower, HANDOFF_PHRASES):
        return "handoff_or_relay"
    if contains_any(lower, PROCEED_PHRASES):
        return "make_it_so"
    if contains_any(lower, RETRY_PHRASES):
        return "retry"
    if contains_any(lower, STOP_PHRASES):
        return "stop"
    if contains_any(lower, UNDO_PHRASES):
        return "undo"
    if contains_any(lower, RESTART_PHRASES):
        return "restart"
    if contains_any(lower, SHIP_PHRASES):
        return "ship"
    return ""


def operator_intent_class(value: Any, *, action: str | None = None) -> str:
    lower = clean_prompt(value).lower()
    requested = action or requested_action(lower)
    button = button_intent(lower)
    if requested == "status":
        return "status"
    if button == "copy_response":
        return "copy_response"
    if button == "simplify_response":
        return "simplify_response"
    if button == "verify_response":
        return "verify_or_audit"
    if button == "dig_deeper":
        return "deep_dive"
    if button == "handoff_or_relay":
        return "handoff_or_relay"
    if requested == "proceed_or_next":
        if any(phrase in lower for phrase in ("continue", "resume")):
            return "continue"
        if any(
            phrase in lower
            for phrase in ("what next", "what's next", "whats next", "wahts next")
        ):
            return "what_next"
        return "proceed"
    if contains_any(lower, RETRY_PHRASES):
        return "retry"
    if contains_any(lower, STOP_PHRASES):
        return "stop"
    if requested == "undo_or_back":
        return "undo_gate"
    if contains_any(lower, RESTART_PHRASES):
        return "deploy_gate"
    if contains_any(lower, SHIP_PHRASES):
        return "deploy_gate"
    if "debug" in lower or "why did" in lower or "what failed" in lower:
        return "debug"
    if requested == "benchmark_or_optimizer":
        return "benchmark"
    return "operator_prompt"


def deterministic_local_verifier_block(
    value: Any,
    *,
    action: str = "",
    intent_class: str = "",
) -> str:
    if is_broad_planning(value):
        return "broad_planning_request"
    if action in {
        "approval_boundary",
        "benchmark_or_optimizer",
        "copy_response",
        "dig_deeper",
        "handoff_or_relay",
        "proceed_or_next",
        "simplify_response",
        "undo_or_back",
        "verify_response",
    }:
        return f"deterministic_action_{action}"
    if intent_class in {
        "approval_gate",
        "benchmark",
        "bounded_edit",
        "copy_response",
        "continue",
        "deep_dive",
        "deploy_gate",
        "handoff_or_relay",
        "proceed",
        "retry",
        "simplify_response",
        "stop",
        "undo_gate",
        "verify_or_audit",
        "what_next",
    }:
        return f"deterministic_intent_{intent_class}"
    return ""


def classify_key_terms(value: Any) -> dict[str, Any]:
    action = requested_action(value)
    intent = operator_intent_class(value, action=action)
    return {
        "schema": "norman.tui-route-intent.key-terms.v1",
        "broad_planning": is_broad_planning(value),
        "quick_status": is_quick_status(value),
        "route_status_diagnostic": is_route_status_diagnostic(value),
        "button_intent": button_intent(value),
        "requested_action": action,
        "operator_intent_class": intent,
        "deterministic_block": deterministic_local_verifier_block(
            value,
            action=action,
            intent_class=intent,
        ),
    }
