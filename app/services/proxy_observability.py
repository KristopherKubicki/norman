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
        "local_execution": _flag(norman.get("local_execution")),
        "cloud_forwarding": _flag(norman.get("cloud_forwarding")),
        "cloud_proxy": _flag(route.get("cloud_proxy")),
        "target_worker": _clean(norllama.get("target_worker")),
        "gateway_selected_worker": _clean(norllama.get("gateway_selected_worker")),
        "observed_worker": _clean(norllama.get("observed_worker")),
        "observed_worker_source": _clean(norllama.get("observed_worker_source")),
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
        "cloud_forward_count": cloud_forward_count,
        "cloud_proxy_count": cloud_proxy_count,
        "workerless_local_success_count": workerless_count,
        "local_route_rate_pct": _pct(local_count, successful),
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
                "id": "cloud-tokens",
                "label": "Cloud/proxy tokens",
                "value": summary["cloud_tokens"],
                "unit": "tokens",
                "tone": "alert" if summary["cloud_tokens"] else "ok",
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
