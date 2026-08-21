from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any, Mapping

from app.services.run_health import evaluate_proxy_run_health


MAX_EVENTS = 500
EVENT_LOG_ENV = "NORMAN_PROXY_EVENT_LOG"
EVENT_LOG_MAX_BYTES_ENV = "NORMAN_PROXY_EVENT_LOG_MAX_BYTES"
RUNAWAY_GUARD_ENV = "NORMAN_PROXY_RUNAWAY_GUARD_ENABLED"
DEFAULT_EVENT_LOG_PATH = Path("/var/lib/norman/state/proxy-events.jsonl")
DEFAULT_EVENT_LOG_MAX_BYTES = 5 * 1024 * 1024
DISABLED_EVENT_LOG_VALUES = frozenset({"0", "false", "none", "off", "disabled"})
TOOL_CHAIN_SCHEMA = "norman.responses-tool-chain.v1"
PROMPT_CONTEXT_SCHEMA = "norman.responses-prompt-context.v1"
TOOL_CHAIN_TURN_TYPES = frozenset({"after_tool_result", "initial_or_text"})
TOOL_CHAIN_OUTCOMES = frozenset(
    {
        "final_after_tool",
        "final_without_tool",
        "invalid_or_unresolved",
        "tool_call",
    }
)
TOOL_CHAIN_WATCHDOG_STATES = frozenset(
    {
        "normal",
        "not_applied",
        "not_required",
        "passthrough",
        "repaired",
        "exhausted",
    }
)
BRIDGE_MODES = frozenset({"transparent", "governed"})
BRIDGE_TOOL_TRANSPORTS = frozenset({"bedrock_mantle_responses", "local_text_adapter"})
BRIDGE_STATE_RETENTIONS = frozenset({"ephemeral", "session"})
PROMPT_CONTEXT_GROUPS = (
    "history",
    "tool_contract",
    "structured_output",
    "current_input",
)
PROMPT_CONTEXT_GROUP_FIELDS = (
    "message_count",
    "chars",
    "tool_output_chars",
    "function_call_chars",
    "text_chars",
)
SAFE_TOOL_CHAIN_CALL_NAMES = frozenset({"tool_search"})
LOCAL_TOOL_CHAIN_CALL_NAMES = {
    "apply_patch": "local_file_patch",
    "exec_command": "local_shell",
    "write_stdin": "local_process_input",
}

_LOCK = threading.RLock()
_EVENT_LOG_LOCK = threading.RLock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_EVENTS_RESTORED = False


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    lowered = _lower(value)
    if not lowered:
        return default
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _bounded_int(value: Any, *, maximum: int = 1_000_000) -> int:
    return min(_int(value), maximum)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, Mapping) else {}


def _route_receipt(response: Mapping[str, Any]) -> dict[str, Any]:
    norman = _mapping(response.get("norman"))
    direct = _mapping(norman.get("route_receipt"))
    if direct:
        return direct
    return _nested(norman, "facade_receipt", "route_receipt")


def _safe_tool_chain_call_name(value: Any) -> str:
    """Classify a returned tool name without retaining arbitrary model output."""

    name = _lower(value)
    if name in SAFE_TOOL_CHAIN_CALL_NAMES:
        return name
    if name in LOCAL_TOOL_CHAIN_CALL_NAMES:
        return LOCAL_TOOL_CHAIN_CALL_NAMES[name]
    if name.startswith("ops_openbrand."):
        suffix = name.removeprefix("ops_openbrand.")
        if suffix and suffix.replace("_", "").replace(".", "").isalnum():
            return f"ops_openbrand.{suffix}"
    if name.startswith("mcp__"):
        return "internal_mcp"
    return "connected_tool"


def _safe_response_tool_call_names(response: Mapping[str, Any]) -> list[str]:
    """Return at most eight sanitized function-call names from a response."""

    names: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, Mapping):
            continue
        if _clean(item.get("type")) != "function_call":
            continue
        name = _safe_tool_chain_call_name(item.get("name"))
        if name in names:
            continue
        names.append(name)
        if len(names) == 8:
            break
    return names


def _safe_identifier(value: Any, *, maximum: int = 192) -> str:
    """Keep model, provider, and error-code labels bounded and display-safe."""

    candidate = _clean(value)
    if not candidate:
        return ""
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@+-"
    )
    if any(character not in allowed for character in candidate):
        return "unknown"
    return candidate[:maximum]


def _safe_prompt_context_metadata(compatibility: Mapping[str, Any]) -> dict[str, Any]:
    """Keep numerical prompt sizing details without retaining model content."""

    prompt_context = _mapping(compatibility.get("prompt_context"))
    if _clean(prompt_context.get("schema")) != PROMPT_CONTEXT_SCHEMA:
        return {}
    raw_groups = _mapping(prompt_context.get("groups"))
    groups: dict[str, dict[str, int]] = {}
    for name in PROMPT_CONTEXT_GROUPS:
        raw_group = _mapping(raw_groups.get(name))
        groups[name] = {
            field: _bounded_int(
                raw_group.get(field),
                maximum=10_000 if field == "message_count" else 4_000_000,
            )
            for field in PROMPT_CONTEXT_GROUP_FIELDS
        }
    return {
        "schema": PROMPT_CONTEXT_SCHEMA,
        "transport": (
            _clean(prompt_context.get("transport"))
            if _clean(prompt_context.get("transport")) in BRIDGE_TOOL_TRANSPORTS
            else "unknown"
        ),
        "groups": groups,
        "total_message_count": _bounded_int(
            prompt_context.get("total_message_count"), maximum=10_000
        ),
        "total_content_chars": _bounded_int(
            prompt_context.get("total_content_chars"), maximum=4_000_000
        ),
        "rendered_prompt_chars": _bounded_int(
            prompt_context.get("rendered_prompt_chars"), maximum=4_000_000
        ),
    }


def _safe_bridge_metadata(
    response: Mapping[str, Any],
    error: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract a bounded bridge receipt without retaining request content."""

    for source in (response, error):
        norman = _mapping(source.get("norman"))
        compatibility = _mapping(norman.get("responses_compatibility"))
        budget = _mapping(norman.get("output_token_budget"))
        if not compatibility and not budget:
            continue
        route = _mapping(norman.get("route"))
        fallback = _mapping(norman.get("cloud_fallback"))
        bridge_mode = _clean(compatibility.get("tool_bridge_mode"))
        tool_transport = _clean(compatibility.get("tool_transport"))
        state_retention = _clean(compatibility.get("state_retention"))
        provider = _safe_identifier(
            route.get("selected_provider") or fallback.get("fallback_provider")
        )
        model = _safe_identifier(
            route.get("selected_model")
            or source.get("model")
            or fallback.get("fallback_model")
        )
        return {
            "mode": bridge_mode if bridge_mode in BRIDGE_MODES else "unknown",
            "tool_transport": (
                tool_transport
                if tool_transport in BRIDGE_TOOL_TRANSPORTS
                else "unknown"
            ),
            "state_retention": (
                state_retention
                if state_retention in BRIDGE_STATE_RETENTIONS
                else "unknown"
            ),
            "effective_backend": {
                "provider": provider or "unknown",
                "model": model or "unknown",
            },
            "output_token_budget": {
                "requested": _bounded_int(budget.get("requested")),
                "effective": _bounded_int(budget.get("effective")),
                "maximum": _bounded_int(budget.get("maximum")),
            },
            "prompt_context": _safe_prompt_context_metadata(compatibility),
            "fallback_reason": _safe_identifier(
                fallback.get("local_failure_code"), maximum=96
            ),
        }
    return {}


def _tool_chain_completion_classification(outcome: str) -> str:
    """Make terminal-vs-continuation state explicit in event records."""

    if outcome == "tool_call":
        return "continuation_required"
    if outcome == "final_after_tool":
        return "completed_after_tool"
    if outcome == "final_without_tool":
        return "completed_without_tool"
    if outcome == "invalid_or_unresolved":
        return "unresolved"
    return "unknown"


def _safe_tool_chain_metadata(
    response: Mapping[str, Any],
    error: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract only bounded, non-content tool-chain observability fields."""

    raw_tool_chain: dict[str, Any] = {}
    for source in (response, error):
        norman = _mapping(source.get("norman"))
        compatibility = _mapping(norman.get("responses_compatibility"))
        candidate = _mapping(compatibility.get("tool_chain"))
        if candidate:
            raw_tool_chain = candidate
            break
    if _clean(raw_tool_chain.get("schema")) != TOOL_CHAIN_SCHEMA:
        return {}

    watchdog = _mapping(raw_tool_chain.get("watchdog"))
    turn_type = _clean(raw_tool_chain.get("turn_type"))
    outcome = _clean(raw_tool_chain.get("outcome"))
    watchdog_state = _clean(watchdog.get("state"))
    safe_outcome = outcome if outcome in TOOL_CHAIN_OUTCOMES else "unknown"
    return {
        "schema": TOOL_CHAIN_SCHEMA,
        "turn_type": turn_type if turn_type in TOOL_CHAIN_TURN_TYPES else "unknown",
        "chain_depth": _int(raw_tool_chain.get("chain_depth")),
        "tool_results_supplied": _int(raw_tool_chain.get("tool_results_supplied")),
        "tool_results_matched": _int(raw_tool_chain.get("tool_results_matched")),
        "tool_calls_returned": _int(raw_tool_chain.get("tool_calls_returned")),
        "tool_call_names": _safe_response_tool_call_names(response),
        "outcome": safe_outcome,
        "completion_classification": _tool_chain_completion_classification(
            safe_outcome
        ),
        "watchdog_state": (
            watchdog_state
            if watchdog_state in TOOL_CHAIN_WATCHDOG_STATES
            else "unknown"
        ),
        "watchdog_attempts": _int(watchdog.get("attempts")),
    }


def _sanitized_error_payload(error: Mapping[str, Any]) -> dict[str, Any]:
    """Keep normal error metadata while excluding raw tool-chain content."""

    payload = dict(error)
    norman = _mapping(payload.get("norman"))
    if not norman:
        return payload
    compatibility = _mapping(norman.get("responses_compatibility"))
    if "tool_chain" not in compatibility:
        return payload
    compatibility.pop("tool_chain", None)
    if compatibility:
        norman["responses_compatibility"] = compatibility
    else:
        norman.pop("responses_compatibility", None)
    payload["norman"] = norman
    return payload


def _receipt_audit_passed(receipt: Mapping[str, Any]) -> bool:
    audit = _mapping(receipt.get("receipt_audit"))
    return _flag(audit.get("pass")) and _lower(audit.get("status")) == "pass"


def _completion_gate_passed(receipt: Mapping[str, Any]) -> bool:
    gate = _mapping(receipt.get("completion_gate"))
    return _flag(gate.get("gate_passed"))


def _release_proof_passed(event: Mapping[str, Any]) -> bool:
    return (
        event.get("status") == "success"
        and _flag(event.get("local_execution"))
        and not _flag(event.get("cloud_forwarding"))
        and not _flag(event.get("cloud_proxy"))
        and bool(_clean(event.get("request_id")))
        and bool(_clean(event.get("observed_worker")))
        and bool(_clean(event.get("route_receipt_present")))
        and _flag(event.get("receipt_audit_passed"))
        and _flag(event.get("completion_gate_passed"))
        and _clean(event.get("execution_mode")) != "unknown"
        and _clean(event.get("usage_bucket")) == "offline_local"
        and _flag(event.get("policy_integrity_valid"))
    )


def _prompt_text(payload: Mapping[str, Any]) -> str:
    messages = payload.get("messages")
    if isinstance(messages, list):
        parts = []
        for item in messages:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
        return "\n".join(parts)
    raw_input = payload.get("input", payload.get("prompt", ""))
    if isinstance(raw_input, str):
        return raw_input
    if isinstance(raw_input, list):
        return json.dumps(raw_input, sort_keys=True, default=str)
    return ""


def request_fingerprint(payload: Mapping[str, Any]) -> dict[str, Any]:
    text = _prompt_text(payload)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    metadata = _mapping(payload.get("metadata"))
    explicit_workflow_value = _clean(
        payload.get("workflow_id")
        or payload.get("thread_id")
        or payload.get("conversation_id")
        or metadata.get("workflow_id")
        or metadata.get("thread_id")
    )
    previous_response_id = _clean(payload.get("previous_response_id"))
    workflow_value = explicit_workflow_value or previous_response_id
    workflow_scope = (
        "explicit"
        if explicit_workflow_value
        else ("previous_response" if previous_response_id else "unscoped")
    )
    tools = payload.get("tools")
    tool_types = sorted(
        _clean(item.get("type")) or "unknown"
        for item in tools or []
        if isinstance(item, Mapping)
    )
    shape = {
        "endpoint_family": (
            "responses" if "previous_response_id" in payload else "chat"
        ),
        "has_previous_response": bool(_clean(payload.get("previous_response_id"))),
        "message_count": len(payload.get("messages") or [])
        if isinstance(payload.get("messages"), list)
        else 0,
        "model": _safe_identifier(payload.get("model")),
        "tool_count": len(tool_types),
        "tool_types": tool_types,
    }
    shape_digest = hashlib.sha256(
        json.dumps(shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "prompt_sha256": digest,
        "request_shape_sha256": shape_digest,
        "workflow_sha256": (
            hashlib.sha256(workflow_value.encode("utf-8")).hexdigest()
            if workflow_value
            else ""
        ),
        "workflow_scope": workflow_scope,
        "prompt_chars": len(text),
        "message_count": shape["message_count"],
        "tool_count": shape["tool_count"],
    }


def proxy_run_admission(
    payload: Mapping[str, Any],
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Stop a known-bad explicit workflow before another model invocation."""

    fingerprint = request_fingerprint(payload)
    enabled = _flag(os.environ.get(RUNAWAY_GUARD_ENV), default=True)
    workflow_hash = _clean(fingerprint.get("workflow_sha256"))
    workflow_scope = _clean(fingerprint.get("workflow_scope"))
    decision = {
        "schema": "norman.proxy.run-admission.v1",
        "enabled": enabled,
        "allowed": True,
        "action": "allow",
        "reason_code": "healthy_or_unscoped",
        "workflow_sha256": workflow_hash,
        "workflow_scope": workflow_scope,
        "run_health": {},
    }
    if not enabled:
        decision.update(
            {
                "action": "disabled",
                "reason_code": "guard_disabled",
            }
        )
        return decision
    if workflow_scope != "explicit" or not workflow_hash:
        return decision

    events = [
        event
        for event in proxy_events_snapshot(limit=limit)
        if _clean(event.get("workflow_sha256")) == workflow_hash
    ]
    run_health = evaluate_proxy_run_health(events)
    decision["run_health"] = run_health
    if run_health.get("state") == "stop":
        decision.update(
            {
                "allowed": False,
                "action": "stop",
                "reason_code": "runaway_stop_required",
            }
        )
    return decision


def _usage_from_response(response: Mapping[str, Any]) -> dict[str, int]:
    usage = _mapping(response.get("usage"))
    total = _int(usage.get("total_tokens"))
    prompt = _int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _int(usage.get("completion_tokens") or usage.get("output_tokens"))
    if not total:
        total = prompt + completion
    norman = _mapping(response.get("norman"))
    local = total if _flag(norman.get("local_execution")) else 0
    cloud_forwarding = _flag(norman.get("cloud_forwarding"))
    cloud_proxy = _flag(
        _nested(norman, "route", "norman_route", "route").get("cloud_proxy")
    )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "local_tokens": local,
        "cloud_llm_tokens": total if cloud_forwarding and not cloud_proxy else 0,
        "cloud_proxy_tokens": total if cloud_proxy else 0,
        "search_tokens": 0,
    }


def _event_log_path() -> Path | None:
    configured = _clean(os.environ.get(EVENT_LOG_ENV))
    if configured.lower() in DISABLED_EVENT_LOG_VALUES:
        return None
    return Path(configured).expanduser() if configured else DEFAULT_EVENT_LOG_PATH


def _event_log_max_bytes() -> int:
    try:
        configured = int(os.environ.get(EVENT_LOG_MAX_BYTES_ENV, 0) or 0)
    except (TypeError, ValueError):
        configured = 0
    return max(
        4096,
        min(configured or DEFAULT_EVENT_LOG_MAX_BYTES, 100 * 1024 * 1024),
    )


def _rotate_event_log(path: Path, *, incoming_bytes: int) -> None:
    """Keep a current event log and one prior generation."""

    try:
        if not path.exists():
            return
        if path.stat().st_size + incoming_bytes <= _event_log_max_bytes():
            return
        previous = path.with_name(f"{path.name}.1")
        previous.unlink(missing_ok=True)
        path.replace(previous)
    except OSError:
        return


def _append_jsonl(event: Mapping[str, Any]) -> None:
    path = _event_log_path()
    if path is None:
        return
    try:
        serialized = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        with _EVENT_LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_event_log(path, incoming_bytes=len(serialized.encode("utf-8")))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(serialized)
    except OSError:
        # Observability must never break the proxy path. The in-memory ring still
        # exposes current process evidence when durable logging is unavailable.
        return


def _read_event_log(path: Path) -> list[dict[str, Any]]:
    records: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, Mapping):
                    records.append(dict(value))
    except OSError:
        return []
    return list(records)


def restore_proxy_events_from_log(*, force: bool = False) -> int:
    """Restore the bounded durable event window after a facade restart."""

    global _EVENTS_RESTORED
    with _LOCK:
        if _EVENTS_RESTORED and not force:
            return 0
        existing = list(_EVENTS)

    path = _event_log_path()
    restored: list[dict[str, Any]] = []
    if path is not None:
        previous = path.with_name(f"{path.name}.1")
        with _EVENT_LOG_LOCK:
            restored.extend(_read_event_log(previous))
            restored.extend(_read_event_log(path))

    with _LOCK:
        if _EVENTS_RESTORED and not force:
            return 0
        merged: dict[str, dict[str, Any]] = {}
        for event in [*restored, *existing, *list(_EVENTS)]:
            event_id = _clean(event.get("event_id"))
            key = event_id or json.dumps(event, sort_keys=True, default=str)
            merged[key] = event
        ordered = sorted(
            merged.values(),
            key=lambda event: (
                float(event.get("created_at") or 0),
                _clean(event.get("event_id")),
            ),
        )[-MAX_EVENTS:]
        _EVENTS.clear()
        _EVENTS.extend(ordered)
        _EVENTS_RESTORED = True
    return len(restored)


def _client_from_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    headers = headers or {}
    normalized = {_lower(key): _clean(value) for key, value in headers.items()}
    client = (
        normalized.get("x-norman-client")
        or normalized.get("x-codex-client")
        or normalized.get("user-agent")
        or "unknown"
    )
    return {
        "client": client,
        "team": normalized.get("x-norman-team", ""),
        "user": normalized.get("x-norman-user", ""),
    }


def record_proxy_event(
    *,
    endpoint: str,
    method: str,
    request_id: str = "",
    status: str,
    http_status: int,
    payload: Mapping[str, Any] | None = None,
    response: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
    headers: Mapping[str, Any] | None = None,
    latency_ms: float | int = 0,
) -> dict[str, Any]:
    payload = payload or {}
    response = response or {}
    norman = _mapping(response.get("norman"))
    route_envelope = _mapping(norman.get("route"))
    gateway = _mapping(norman.get("gateway"))
    route = _nested(route_envelope, "norman_route", "route")
    classification = _nested(route_envelope, "norman_route", "classification")
    strategy = _nested(route_envelope, "norman_route", "routing_strategy")
    norllama = _mapping(norman.get("norllama"))
    receipt = _route_receipt(response)
    receipt_audit = _mapping(receipt.get("receipt_audit"))
    completion_gate = _mapping(receipt.get("completion_gate"))
    usage = _usage_from_response(response)
    raw_error_payload = dict(error or {})
    tool_chain = _safe_tool_chain_metadata(response, raw_error_payload)
    bridge = _safe_bridge_metadata(response, raw_error_payload)
    error_payload = _sanitized_error_payload(raw_error_payload)
    error_norman = _mapping(error_payload.get("norman"))
    now = time.time()
    event = {
        "schema": "norman.proxy.event.v1",
        "event_id": f"proxy-{uuid.uuid4().hex}",
        "created_at": now,
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "endpoint": endpoint,
        "method": method.upper(),
        "request_id": request_id
        or _clean(norman.get("request_id"))
        or _clean(error_norman.get("request_id")),
        "gateway_route": _clean(norman.get("gateway_route"))
        or _clean(gateway.get("gateway_route")),
        "source_tui": _clean(gateway.get("source_tui")),
        "policy_scope": _clean(gateway.get("policy_scope")),
        "gateway_request_id": _clean(receipt.get("gateway_request_id")),
        "invocation_id": _clean(receipt.get("invocation_id")),
        "job_id": _clean(receipt.get("job_id")),
        "status": status,
        "http_status": int(http_status),
        **_client_from_headers(headers),
        "requested_model": _clean(payload.get("model"))
        or _clean(error_norman.get("requested_model")),
        "selected_runtime": _clean(route_envelope.get("selected_runtime")),
        "selected_provider": _clean(route_envelope.get("selected_provider")),
        "selected_model": _clean(route_envelope.get("selected_model"))
        or _clean(response.get("model"))
        or _clean(error_norman.get("selected_model")),
        "intent": _clean(classification.get("intent")),
        "task_kind": _clean(classification.get("task_kind")),
        "routing_strategy": _clean(strategy.get("strategy")),
        "execution_mode": _clean(receipt.get("execution_mode")) or "unknown",
        "local_execution": _flag(norman.get("local_execution")),
        "cloud_forwarding": _flag(norman.get("cloud_forwarding")),
        "cloud_proxy": _flag(route.get("cloud_proxy")),
        "target_worker": _clean(norllama.get("target_worker")),
        "gateway_selected_worker": _clean(norllama.get("gateway_selected_worker")),
        "observed_worker": _clean(norllama.get("observed_worker")),
        "observed_worker_source": _clean(norllama.get("observed_worker_source")),
        "route_receipt_present": bool(receipt),
        "receipt_audit_passed": _receipt_audit_passed(receipt),
        "receipt_audit_status": _clean(receipt_audit.get("status")),
        "receipt_audit_failures": list(receipt_audit.get("failures") or [])
        if isinstance(receipt_audit.get("failures"), list)
        else [],
        "completion_gate_passed": _completion_gate_passed(receipt),
        "output_shape": _clean(receipt.get("output_shape")),
        "verifier_result": _clean(receipt.get("verifier_result")),
        "usage_bucket": _clean(receipt.get("usage_bucket")),
        "policy_id": _clean(receipt.get("policy_id")),
        "policy_hash": _clean(receipt.get("policy_hash")),
        "policy_lifecycle_state": _clean(receipt.get("policy_lifecycle_state")),
        "policy_integrity_valid": _flag(receipt.get("policy_integrity_valid")),
        "policy_default_route_allowed": _flag(
            receipt.get("policy_default_route_allowed")
        ),
        "policy_production_routes_allowed": _flag(
            receipt.get("policy_production_routes_allowed")
        ),
        "request_production_route_eligible": _flag(
            receipt.get("request_production_route_eligible")
        ),
        "route_authority": _clean(receipt.get("route_authority")),
        "usage": usage,
        "tool_chain": tool_chain,
        "bridge": bridge,
        "latency_ms": round(float(latency_ms or 0), 3),
        "error": error_payload,
        "error_code": _clean(error_payload.get("code")),
        "retryable": _flag(error_norman.get("retryable")),
        **request_fingerprint(payload),
    }
    with _LOCK:
        _EVENTS.append(event)
    _append_jsonl(event)
    return event


def reset_proxy_events() -> None:
    global _EVENTS_RESTORED
    with _LOCK:
        _EVENTS.clear()
        _EVENTS_RESTORED = True


def proxy_events_snapshot(limit: int = 100) -> list[dict[str, Any]]:
    restore_proxy_events_from_log()
    limit = max(1, min(int(limit or 100), MAX_EVENTS))
    with _LOCK:
        return list(_EVENTS)[-limit:]


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 2)


def proxy_observability_summary(limit: int = 100) -> dict[str, Any]:
    events = proxy_events_snapshot(limit=limit)
    total = len(events)
    statuses = Counter(_clean(event.get("status")) or "unknown" for event in events)
    error_codes = Counter(
        _clean(event.get("error_code"))
        for event in events
        if _clean(event.get("error_code"))
    )
    by_endpoint = Counter(_clean(event.get("endpoint")) for event in events)
    by_client = Counter(_clean(event.get("client")) for event in events)
    by_worker = Counter(
        _clean(event.get("observed_worker")) or "unknown" for event in events
    )
    local_count = sum(1 for event in events if _flag(event.get("local_execution")))
    cloud_forward_count = sum(
        1 for event in events if _flag(event.get("cloud_forwarding"))
    )
    cloud_proxy_count = sum(1 for event in events if _flag(event.get("cloud_proxy")))
    workerless_count = sum(
        1
        for event in events
        if event.get("status") == "success"
        and _flag(event.get("local_execution"))
        and not _clean(event.get("observed_worker"))
    )
    release_proof_count = sum(1 for event in events if _release_proof_passed(event))
    route_receipt_count = sum(
        1 for event in events if _flag(event.get("route_receipt_present"))
    )
    receipt_audit_pass_count = sum(
        1 for event in events if _flag(event.get("receipt_audit_passed"))
    )
    completion_gate_pass_count = sum(
        1 for event in events if _flag(event.get("completion_gate_passed"))
    )
    receiptless_success_count = sum(
        1
        for event in events
        if event.get("status") == "success"
        and not _flag(event.get("route_receipt_present"))
    )
    audit_failed_success_count = sum(
        1
        for event in events
        if event.get("status") == "success"
        and _flag(event.get("route_receipt_present"))
        and not _flag(event.get("receipt_audit_passed"))
    )
    completion_gate_failed_success_count = sum(
        1
        for event in events
        if event.get("status") == "success"
        and _flag(event.get("route_receipt_present"))
        and not _flag(event.get("completion_gate_passed"))
    )
    unknown_execution_mode_success_count = sum(
        1
        for event in events
        if event.get("status") == "success"
        and _clean(event.get("execution_mode")) == "unknown"
    )
    request_id_missing_success_count = sum(
        1
        for event in events
        if event.get("status") == "success" and not _clean(event.get("request_id"))
    )
    capacity_unavailable_count = sum(
        1
        for event in events
        if event.get("status") == "capacity_unavailable"
        or _clean(event.get("error_code")).startswith("local_capacity_")
    )
    local_timeout_count = sum(
        1
        for event in events
        if _clean(event.get("error_code")) == "local_model_timeout"
    )
    local_gateway_error_count = sum(
        1
        for event in events
        if event.get("status") == "local_gateway_error"
        or _clean(event.get("error_code")).startswith("local_gateway_")
    )
    tool_chain_events = [
        _mapping(event.get("tool_chain"))
        for event in events
        if _clean(_mapping(event.get("tool_chain")).get("schema")) == TOOL_CHAIN_SCHEMA
    ]
    tool_chain_repaired_count = sum(
        1
        for tool_chain in tool_chain_events
        if _clean(tool_chain.get("watchdog_state")) == "repaired"
    )
    tool_chain_exhausted_count = sum(
        1
        for tool_chain in tool_chain_events
        if _clean(tool_chain.get("watchdog_state")) == "exhausted"
    )
    bridge_events = [
        _mapping(event.get("bridge"))
        for event in events
        if _mapping(event.get("bridge"))
    ]
    bridge_modes = Counter(
        _clean(bridge.get("mode")) or "unknown" for bridge in bridge_events
    )
    bridge_fallback_count = sum(
        1 for bridge in bridge_events if _clean(bridge.get("fallback_reason"))
    )
    usage_totals = {
        "local_tokens": sum(
            _int(_mapping(event.get("usage")).get("local_tokens")) for event in events
        ),
        "cloud_llm_tokens": sum(
            _int(_mapping(event.get("usage")).get("cloud_llm_tokens"))
            for event in events
        ),
        "cloud_proxy_tokens": sum(
            _int(_mapping(event.get("usage")).get("cloud_proxy_tokens"))
            for event in events
        ),
        "search_tokens": sum(
            _int(_mapping(event.get("usage")).get("search_tokens")) for event in events
        ),
        "total_tokens": sum(
            _int(_mapping(event.get("usage")).get("total_tokens")) for event in events
        ),
    }
    successful = statuses.get("success", 0)
    cloud_tokens = usage_totals["cloud_llm_tokens"] + usage_totals["cloud_proxy_tokens"]
    run_health = evaluate_proxy_run_health(events)
    summary = {
        "schema": "norman.proxy.observability-summary.v1",
        "event_count": total,
        "window_limit": max(1, min(int(limit or 100), MAX_EVENTS)),
        "statuses": dict(statuses),
        "error_codes": dict(error_codes),
        "by_endpoint": dict(by_endpoint),
        "by_client": dict(by_client),
        "by_worker": dict(by_worker),
        "local_execution_count": local_count,
        "release_proof_success_count": release_proof_count,
        "route_receipt_count": route_receipt_count,
        "receipt_audit_pass_count": receipt_audit_pass_count,
        "completion_gate_pass_count": completion_gate_pass_count,
        "receiptless_success_count": receiptless_success_count,
        "audit_failed_success_count": audit_failed_success_count,
        "completion_gate_failed_success_count": completion_gate_failed_success_count,
        "unknown_execution_mode_success_count": unknown_execution_mode_success_count,
        "request_id_missing_success_count": request_id_missing_success_count,
        "capacity_unavailable_count": capacity_unavailable_count,
        "local_timeout_count": local_timeout_count,
        "local_gateway_error_count": local_gateway_error_count,
        "tool_chain_event_count": len(tool_chain_events),
        "tool_chain_repaired_count": tool_chain_repaired_count,
        "tool_chain_exhausted_count": tool_chain_exhausted_count,
        "bridge_event_count": len(bridge_events),
        "bridge_modes": dict(bridge_modes),
        "bridge_fallback_count": bridge_fallback_count,
        "cloud_forward_count": cloud_forward_count,
        "cloud_proxy_count": cloud_proxy_count,
        "workerless_local_success_count": workerless_count,
        "local_route_rate_pct": _pct(local_count, successful),
        "release_proof_rate_pct": _pct(release_proof_count, successful),
        "receipt_audit_coverage_pct": _pct(receipt_audit_pass_count, successful),
        "completion_gate_coverage_pct": _pct(completion_gate_pass_count, successful),
        "cloud_forward_rate_pct": _pct(cloud_forward_count, total),
        "blocked_count": statuses.get("blocked", 0)
        + statuses.get("auth_failed", 0)
        + statuses.get("unsupported", 0),
        "usage_totals": usage_totals,
        "cloud_tokens": cloud_tokens,
        "cloud_token_avoidance_estimate": usage_totals["local_tokens"],
        "run_health": run_health,
        "chart": {
            "recent_local": [
                1 if _flag(event.get("local_execution")) else 0
                for event in events[-40:]
            ],
            "recent_cloud": [
                1
                if _flag(event.get("cloud_forwarding"))
                or _flag(event.get("cloud_proxy"))
                else 0
                for event in events[-40:]
            ],
            "recent_latency_ms": [
                round(float(event.get("latency_ms") or 0), 3) for event in events[-40:]
            ],
        },
    }
    summary["alerts"] = proxy_alerts(summary=summary, events=events)["alerts"]
    return summary


def proxy_alerts(
    *,
    summary: Mapping[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = events if events is not None else proxy_events_snapshot(limit=100)
    summary = dict(summary or {})
    alerts: list[dict[str, Any]] = []
    if not events:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_no_recent_events",
                "message": "No OpenAI-compatible proxy traffic has been recorded in this process.",
            }
        )
    cloud_count = int(summary.get("cloud_forward_count") or 0) + int(
        summary.get("cloud_proxy_count") or 0
    )
    if cloud_count:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_cloud_route_observed",
                "message": f"{cloud_count} proxy request(s) used cloud forwarding or cloud proxying.",
            }
        )
    workerless = int(summary.get("workerless_local_success_count") or 0)
    if workerless:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_missing_worker_attribution",
                "message": f"{workerless} successful local proxy request(s) missed observed worker attribution.",
            }
        )
    receiptless = int(summary.get("receiptless_success_count") or 0)
    if receiptless:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_missing_route_receipt",
                "message": f"{receiptless} successful proxy request(s) missed canonical route receipts.",
            }
        )
    audit_failed = int(summary.get("audit_failed_success_count") or 0)
    if audit_failed:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_receipt_audit_failed",
                "message": f"{audit_failed} successful proxy request(s) failed receipt audit.",
            }
        )
    gate_failed = int(summary.get("completion_gate_failed_success_count") or 0)
    if gate_failed:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_completion_gate_failed",
                "message": f"{gate_failed} successful proxy request(s) failed completion gate.",
            }
        )
    unknown_mode = int(summary.get("unknown_execution_mode_success_count") or 0)
    if unknown_mode:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_unknown_execution_mode",
                "message": f"{unknown_mode} successful proxy request(s) had unknown execution mode.",
            }
        )
    missing_request_id = int(summary.get("request_id_missing_success_count") or 0)
    if missing_request_id:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_missing_request_id",
                "message": f"{missing_request_id} successful proxy request(s) missed request IDs.",
            }
        )
    auth_failures = sum(1 for event in events if event.get("status") == "auth_failed")
    if auth_failures:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_auth_failures",
                "message": f"{auth_failures} proxy authentication failure(s) were recorded.",
            }
        )
    unsupported = sum(1 for event in events if event.get("status") == "unsupported")
    if unsupported:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_unsupported_client_semantics",
                "message": f"{unsupported} request(s) used unsupported OpenAI/Codex semantics.",
            }
        )
    errors = sum(1 for event in events if event.get("status") == "error")
    if errors:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_execution_errors",
                "message": f"{errors} proxy execution error(s) were recorded.",
            }
        )
    run_health = _mapping(summary.get("run_health"))
    run_health_state = _clean(run_health.get("state"))
    if run_health_state in {"warn", "stop"}:
        signals = [
            _clean(item.get("code"))
            for item in run_health.get("signals") or []
            if isinstance(item, Mapping) and _clean(item.get("code"))
        ]
        alerts.append(
            {
                "severity": "critical" if run_health_state == "stop" else "warn",
                "kind": f"proxy_run_health_{run_health_state}",
                "message": (
                    "Proxy run health recommends "
                    f"{_clean(run_health.get('recommended_action')) or 'inspection'}"
                    + (f": {', '.join(signals)}." if signals else ".")
                ),
            }
        )
    capacity_unavailable = int(summary.get("capacity_unavailable_count") or 0)
    if capacity_unavailable:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_local_capacity_unavailable",
                "message": (
                    f"{capacity_unavailable} local capacity-unavailable event(s) "
                    "were recorded."
                ),
            }
        )
    local_timeouts = int(summary.get("local_timeout_count") or 0)
    if local_timeouts:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_local_model_timeouts",
                "message": f"{local_timeouts} local model timeout(s) were recorded.",
            }
        )
    gateway_errors = int(summary.get("local_gateway_error_count") or 0)
    if gateway_errors:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_local_gateway_errors",
                "message": f"{gateway_errors} local gateway error(s) were recorded.",
            }
        )
    tool_chain_repaired = int(summary.get("tool_chain_repaired_count") or 0)
    if tool_chain_repaired:
        alerts.append(
            {
                "severity": "warn",
                "kind": "proxy_tool_chain_watchdog_repaired",
                "message": (
                    f"{tool_chain_repaired} tool-chain continuation(s) required "
                    "the bounded repair."
                ),
            }
        )
    tool_chain_exhausted = int(summary.get("tool_chain_exhausted_count") or 0)
    if tool_chain_exhausted:
        alerts.append(
            {
                "severity": "critical",
                "kind": "proxy_tool_chain_watchdog_exhausted",
                "message": (
                    f"{tool_chain_exhausted} tool-chain continuation(s) remained "
                    "invalid after the bounded repair."
                ),
            }
        )
    return {
        "schema": "norman.proxy.alerts.v1",
        "alert_count": len(alerts),
        "alerts": alerts,
    }


def proxy_dashboard(limit: int = 100) -> dict[str, Any]:
    summary = proxy_observability_summary(limit=limit)
    return {
        "schema": "norman.proxy.dashboard.v1",
        "title": "Norman OpenAI-Compatible Proxy",
        "summary": summary,
        "widgets": [
            {
                "id": "local-route-rate",
                "label": "Local route rate",
                "value": summary["local_route_rate_pct"],
                "unit": "%",
                "tone": "ok"
                if summary["local_route_rate_pct"] >= 90 or not summary["event_count"]
                else "warn",
            },
            {
                "id": "release-proof-rate",
                "label": "Release-proof rate",
                "value": summary["release_proof_rate_pct"],
                "unit": "%",
                "tone": "ok"
                if summary["release_proof_rate_pct"] >= 90 or not summary["event_count"]
                else "warn",
            },
            {
                "id": "cloud-tokens",
                "label": "Cloud/proxy tokens",
                "value": summary["cloud_tokens"],
                "unit": "tokens",
                "tone": "alert" if summary["cloud_tokens"] else "ok",
            },
            {
                "id": "receipt-audit",
                "label": "Receipt audit coverage",
                "value": summary["receipt_audit_coverage_pct"],
                "unit": "%",
                "tone": "ok"
                if summary["receipt_audit_coverage_pct"] >= 90
                or not summary["event_count"]
                else "alert",
            },
            {
                "id": "observed-workers",
                "label": "Observed workers",
                "value": len(
                    [
                        worker
                        for worker in summary["by_worker"]
                        if worker and worker != "unknown"
                    ]
                ),
                "unit": "workers",
                "tone": "ok",
            },
            {
                "id": "alerts",
                "label": "Proxy alerts",
                "value": len(summary["alerts"]),
                "unit": "alerts",
                "tone": "alert" if summary["alerts"] else "ok",
            },
        ],
    }
