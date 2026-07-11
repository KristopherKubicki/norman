from __future__ import annotations

import time
from typing import Any, Iterable

DEFAULT_COOLDOWN_STATUSES = {
    "bad-output",
    "empty-response",
    "request-failed",
    "timeout",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _worker_id_from_endpoint(value: Any) -> str:
    text = _clean(value).lower()
    if "192.168.2.151" in text or "2.151" in text:
        return "spark-151"
    if "192.168.2.150" in text or "2.150" in text:
        return "spark-150"
    if "192.168.2.133" in text or "2.133" in text:
        return "mac-mini-133"
    return ""


def normalize_route_outcome(value: Any) -> dict[str, Any]:
    item = _json_dict(value)
    status = _lower(item.get("status")) or "unknown"
    ok = bool(item.get("ok")) and status in {"ok", "success"}
    metadata = _json_dict(item.get("metadata"))
    worker_endpoint = _clean(item.get("worker_endpoint"))
    upstream = _clean(item.get("upstream"))
    endpoint = _clean(item.get("endpoint"))
    return {
        "schema": "norman.norllama.route-outcome.v1",
        "recorded_at": _as_int(item.get("recorded_at")) or int(time.time()),
        "source": _clean(item.get("source")) or "unknown",
        "tui": _clean(item.get("tui") or item.get("agent")),
        "session": _clean(item.get("session")),
        "host": _clean(item.get("host")),
        "status": status,
        "ok": ok,
        "provider": _clean(item.get("provider")) or "norllama",
        "model": _clean(item.get("model")),
        "endpoint": endpoint,
        "adapter": _clean(item.get("adapter")),
        "url": _clean(item.get("url")),
        "worker_id": _clean(item.get("worker_id"))
        or _worker_id_from_endpoint(worker_endpoint or upstream or endpoint),
        "worker_endpoint": worker_endpoint,
        "upstream": upstream,
        "attempts": _clean(item.get("attempts")),
        "latency_ms": _as_int(item.get("latency_ms")),
        "response_chars": _as_int(item.get("response_chars")),
        "input_tokens": _as_int(item.get("input_tokens")),
        "output_tokens": _as_int(item.get("output_tokens")),
        "total_tokens": _as_int(item.get("total_tokens")),
        "reason": _clean(item.get("reason"))[:480],
        "thread_id": _clean(item.get("thread_id")),
        "metadata": metadata,
    }


def route_outcome_event_payload(value: Any) -> dict[str, Any]:
    outcome = normalize_route_outcome(value)
    endpoint = (
        outcome.get("endpoint")
        or outcome.get("worker_endpoint")
        or outcome.get("upstream")
        or ""
    )
    payload = {
        **outcome,
        "outcome": outcome,
        "task_kind": "local_llm_route",
        "selected_lane": "local_llm",
        "selected_provider": outcome.get("provider") or "norllama",
        "selected_runner": "norllama",
        "selected_model": outcome.get("model") or "",
        "selected_endpoint": endpoint,
        "egress_class": "lan",
        "local": True,
        "allowed": bool(outcome.get("ok")),
        "attribution": {
            "worker_id": outcome.get("worker_id") or "",
            "worker_endpoint": outcome.get("worker_endpoint") or "",
            "upstream": outcome.get("upstream") or "",
        },
        "usage": {
            "input_tokens": _as_int(outcome.get("input_tokens")),
            "output_tokens": _as_int(outcome.get("output_tokens")),
            "total_tokens": _as_int(outcome.get("total_tokens")),
        },
    }
    return payload


def outcome_from_event_payload(value: Any) -> dict[str, Any]:
    payload = _json_dict(value)
    return normalize_route_outcome(payload.get("outcome") or payload)


def local_route_cooldown(
    outcomes: Iterable[dict[str, Any]],
    *,
    model: str,
    endpoint: str = "",
    worker_id: str = "",
    cooldown_seconds: int = 900,
    cooldown_statuses: set[str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if cooldown_seconds <= 0:
        return {}
    cooldown_statuses = cooldown_statuses or DEFAULT_COOLDOWN_STATUSES
    clean_model = _clean(model)
    clean_endpoint = _clean(endpoint)
    clean_worker_id = _clean(worker_id)
    current = int(now if now is not None else time.time())
    for raw in reversed(list(outcomes)):
        outcome = normalize_route_outcome(raw)
        if outcome.get("model") != clean_model:
            continue
        if clean_endpoint and outcome.get("endpoint") not in {"", clean_endpoint}:
            continue
        if clean_worker_id and outcome.get("worker_id") not in {"", clean_worker_id}:
            continue
        age = max(0, current - _as_int(outcome.get("recorded_at")))
        if age > cooldown_seconds:
            return {}
        if outcome.get("ok"):
            return {}
        status = _lower(outcome.get("status"))
        if status not in cooldown_statuses:
            continue
        return {
            "active": True,
            "model": clean_model,
            "endpoint": clean_endpoint,
            "status": status,
            "reason": outcome.get("reason") or "",
            "recorded_at": outcome.get("recorded_at"),
            "age_seconds": age,
            "remaining_seconds": max(0, cooldown_seconds - age),
            "worker_id": outcome.get("worker_id") or "",
            "worker_endpoint": outcome.get("worker_endpoint") or "",
            "upstream": outcome.get("upstream") or "",
        }
    return {}


def summarize_route_outcomes(
    values: Iterable[Any],
    *,
    cooldown_seconds: int = 900,
    cooldown_statuses: set[str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    outcomes = [normalize_route_outcome(value) for value in values]
    current = int(now if now is not None else time.time())
    by_model: dict[str, dict[str, Any]] = {}
    by_tui: dict[str, int] = {}
    by_worker: dict[str, int] = {}
    successes = 0
    failures = 0
    for outcome in outcomes:
        if outcome.get("ok"):
            successes += 1
        else:
            failures += 1
        tui = outcome.get("tui") or outcome.get("session") or "unknown"
        by_tui[tui] = by_tui.get(tui, 0) + 1
        worker_id = outcome.get("worker_id") or ""
        if worker_id:
            by_worker[worker_id] = by_worker.get(worker_id, 0) + 1
        model = outcome.get("model") or "unknown"
        bucket = by_model.setdefault(
            model,
            {
                "model": model,
                "ok": 0,
                "fail": 0,
                "last_status": "",
                "last_reason": "",
                "last_recorded_at": 0,
                "last_tui": "",
                "last_worker_id": "",
                "cooldown": {},
            },
        )
        if outcome.get("ok"):
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1
        if _as_int(outcome.get("recorded_at")) >= _as_int(
            bucket.get("last_recorded_at")
        ):
            bucket["last_status"] = outcome.get("status") or ""
            bucket["last_reason"] = outcome.get("reason") or ""
            bucket["last_recorded_at"] = _as_int(outcome.get("recorded_at"))
            bucket["last_tui"] = tui
            bucket["last_worker_id"] = worker_id
            bucket["cooldown"] = local_route_cooldown(
                outcomes,
                model=model,
                cooldown_seconds=cooldown_seconds,
                cooldown_statuses=cooldown_statuses,
                now=current,
            )
    return {
        "schema": "norman.norllama.route-outcomes-summary.v1",
        "count": len(outcomes),
        "ok": successes,
        "fail": failures,
        "cooldown_seconds": max(0, int(cooldown_seconds or 0)),
        "by_tui": by_tui,
        "by_worker": by_worker,
        "models": sorted(
            by_model.values(),
            key=lambda item: _as_int(item.get("last_recorded_at")),
            reverse=True,
        ),
    }
