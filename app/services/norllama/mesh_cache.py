from __future__ import annotations

import copy
import threading
import time
from typing import Any

from app.core.config import settings
from app.services.norllama import gateway

_cache_lock = threading.Lock()
_cached_snapshot: dict[str, Any] | None = None
_cached_at = 0.0
_cached_error = ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _setting_float(
    name: str, default: float, *, minimum: float, maximum: float
) -> float:
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def reset_mesh_cache() -> None:
    global _cached_snapshot, _cached_at, _cached_error
    with _cache_lock:
        _cached_snapshot = None
        _cached_at = 0.0
        _cached_error = ""


def _with_cache_metadata(
    snapshot: dict[str, Any],
    *,
    status: str,
    checked_at: float,
    ttl_seconds: float,
    last_error: str = "",
) -> dict[str, Any]:
    now = time.time()
    payload = copy.deepcopy(snapshot)
    payload["cache"] = {
        "status": status,
        "age_seconds": max(0, int(now - checked_at)),
        "ttl_seconds": int(ttl_seconds),
        "checked_at": checked_at,
        "last_error": _clean(last_error)[:240],
    }
    return payload


def get_mesh_overview(
    *,
    force_refresh: bool = False,
    timeout_seconds: float | None = None,
    ttl_seconds: float | None = None,
    stale_seconds: float | None = None,
) -> dict[str, Any]:
    """Return a cached Norllama mesh snapshot with stale-on-error behavior."""

    global _cached_snapshot, _cached_at, _cached_error
    ttl = (
        float(ttl_seconds)
        if ttl_seconds is not None
        else _setting_float("llm_mesh_cache_ttl_seconds", 15, minimum=0, maximum=3600)
    )
    stale_window = (
        float(stale_seconds)
        if stale_seconds is not None
        else _setting_float(
            "llm_mesh_cache_stale_seconds", 300, minimum=max(ttl, 0), maximum=86400
        )
    )
    now = time.time()
    with _cache_lock:
        cached = copy.deepcopy(_cached_snapshot)
        cached_at = _cached_at
        cached_error = _cached_error
    if cached and not force_refresh and ttl > 0 and now - cached_at <= ttl:
        return _with_cache_metadata(
            cached,
            status="hit",
            checked_at=cached_at,
            ttl_seconds=ttl,
            last_error=cached_error,
        )
    try:
        refreshed = gateway.build_mesh_overview(timeout_seconds=timeout_seconds)
    except Exception as exc:
        error = _clean(exc)
        with _cache_lock:
            cached = copy.deepcopy(_cached_snapshot)
            cached_at = _cached_at
            _cached_error = error
        if cached and now - cached_at <= stale_window:
            return _with_cache_metadata(
                cached,
                status="stale_error",
                checked_at=cached_at,
                ttl_seconds=ttl,
                last_error=error,
            )
        raise
    checked_at = time.time()
    with _cache_lock:
        _cached_snapshot = copy.deepcopy(refreshed)
        _cached_at = checked_at
        _cached_error = ""
    return _with_cache_metadata(
        refreshed,
        status="refresh",
        checked_at=checked_at,
        ttl_seconds=ttl,
    )
