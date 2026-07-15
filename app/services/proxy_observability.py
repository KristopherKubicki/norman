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


MAX_EVENTS = 500
EVENT_LOG_ENV = "NORMAN_PROXY_EVENT_LOG"

_LOCK = threading.RLock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)


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
    return {
        "prompt_sha256": digest,
        "prompt_chars": len(text),
        "message_count": len(payload.get("messages") or [])
        if isinstance(payload.get("messages"), list)
        else 0,
    }


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
    if not configured:
        return None
    return Path(configured).expanduser()


def _append_jsonl(event: Mapping[str, Any]) -> None:
    path = _event_log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    except OSError:
        # Observability must never break the proxy path. The in-memory ring still
        # exposes current process evidence when durable logging is unavailable.
        return


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
    route = _nested(route_envelope, "norman_route", "route")
    classification = _nested(route_envelope, "norman_route", "classification")
    strategy = _nested(route_envelope, "norman_route", "routing_strategy")
    norllama = _mapping(norman.get("norllama"))
    receipt = _route_receipt(response)
    receipt_audit = _mapping(receipt.get("receipt_audit"))
    completion_gate = _mapping(receipt.get("completion_gate"))
    usage = _usage_from_response(response)
    now = time.time()
    event = {
        "schema": "norman.proxy.event.v1",
        "event_id": f"proxy-{uuid.uuid4().hex}",
        "created_at": now,
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "endpoint": endpoint,
        "method": method.upper(),
        "request_id": request_id or _clean(norman.get("request_id")),
        "gateway_request_id": _clean(receipt.get("gateway_request_id")),
        "invocation_id": _clean(receipt.get("invocation_id")),
        "job_id": _clean(receipt.get("job_id")),
        "status": status,
        "http_status": int(http_status),
        **_client_from_headers(headers),
        "requested_model": _clean(payload.get("model")),
        "selected_runtime": _clean(route_envelope.get("selected_runtime")),
        "selected_provider": _clean(route_envelope.get("selected_provider")),
        "selected_model": _clean(route_envelope.get("selected_model"))
        or _clean(response.get("model")),
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
        "latency_ms": round(float(latency_ms or 0), 3),
        "error": dict(error or {}),
        **request_fingerprint(payload),
    }
    with _LOCK:
        _EVENTS.append(event)
    _append_jsonl(event)
    return event


def reset_proxy_events() -> None:
    with _LOCK:
        _EVENTS.clear()


def proxy_events_snapshot(limit: int = 100) -> list[dict[str, Any]]:
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
    summary = {
        "schema": "norman.proxy.observability-summary.v1",
        "event_count": total,
        "window_limit": max(1, min(int(limit or 100), MAX_EVENTS)),
        "statuses": dict(statuses),
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
