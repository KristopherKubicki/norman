from __future__ import annotations

from typing import Any, Mapping

from app.services.norllama.route_policy import (
    ROUTE_POLICY_FALLBACKS,
    ROUTE_POLICY_MODELS,
    ROUTE_POLICY_PLACEMENT,
)


CAPACITY_SCHEMA = "norman.norllama.capacity.v1"
HEAVY_CODING_MODEL = ROUTE_POLICY_MODELS["coding_operator"]
HEAVY_CODING_WORKER_IDS = frozenset(
    {
        str(ROUTE_POLICY_PLACEMENT["primary_brain_worker"]),
        str(ROUTE_POLICY_PLACEMENT["specialist_worker"]),
    }
)
FALLBACK_WORKER_ID = str(ROUTE_POLICY_PLACEMENT["fallback_node"])


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _models(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {_clean(item).lower() for item in value if _clean(item)}


def _is_heavy_coding_model(model: Any) -> bool:
    return _clean(model).lower() == HEAVY_CODING_MODEL.lower()


def _is_eligible_heavy_worker(worker: Mapping[str, Any]) -> bool:
    return _clean(worker.get("id")) in HEAVY_CODING_WORKER_IDS


def _worker_row(
    worker: Mapping[str, Any],
    *,
    selected_model: str,
    eligible: bool,
) -> dict[str, Any]:
    advertised = selected_model.lower() in _models(worker.get("models"))
    row = {
        "id": _clean(worker.get("id")) or "unknown",
        "role": _clean(worker.get("role")) or "unknown",
        "memory_gb": _int(worker.get("memory_gb")),
        "reachable": bool(worker.get("reachable")),
        "status": _clean(worker.get("status")) or "unknown",
        "model_advertised": advertised,
    }
    if not eligible:
        row["reason"] = (
            "ineligible_for_heavy_coding"
            if row["id"] == FALLBACK_WORKER_ID or row["role"] == "fallback"
            else "not_eligible_by_route_policy"
        )
    return row


def heavy_coding_capacity_policy() -> dict[str, list[dict[str, str]]]:
    """Return the stable worker policy included in safe failure payloads."""

    return {
        "eligible_workers": [
            {"id": worker_id, "role": "production"}
            for worker_id in sorted(HEAVY_CODING_WORKER_IDS)
        ],
        "ineligible_workers": [
            {
                "id": FALLBACK_WORKER_ID,
                "reason": "ineligible_for_heavy_coding",
            }
        ],
    }


def unavailable_capacity_snapshot(
    *,
    requested_model: str,
    selected_model: str,
    reason: str,
) -> dict[str, Any]:
    """Return a safe unavailable result when a live mesh probe cannot complete."""

    return {
        "schema": CAPACITY_SCHEMA,
        "available": False,
        "reason": reason,
        "requested_model": requested_model,
        "selected_model": selected_model,
        "frontdoor": {
            "reachable": False,
            "status": "unknown",
            "model_advertised": False,
        },
        **heavy_coding_capacity_policy(),
        "cache": {"status": "unavailable"},
        "cloud_fallback": bool(ROUTE_POLICY_FALLBACKS["allow_cloud_fallback"]),
        "retryable": True,
    }


def build_capacity_snapshot(
    mesh: Mapping[str, Any],
    *,
    requested_model: str,
    selected_model: str,
) -> dict[str, Any]:
    """Build a model-specific capacity view from direct worker probe state."""

    mesh_payload = _mapping(mesh)
    frontdoor = _mapping(mesh_payload.get("frontdoor"))
    workers = [
        _mapping(item)
        for item in mesh_payload.get("workers") or []
        if isinstance(item, Mapping)
    ]
    heavy_coding = _is_heavy_coding_model(selected_model)
    eligible_workers = [
        _worker_row(
            worker,
            selected_model=selected_model,
            eligible=True,
        )
        for worker in workers
        if not heavy_coding or _is_eligible_heavy_worker(worker)
    ]
    ineligible_workers = [
        _worker_row(
            worker,
            selected_model=selected_model,
            eligible=False,
        )
        for worker in workers
        if heavy_coding and not _is_eligible_heavy_worker(worker)
    ]
    cache = _mapping(mesh_payload.get("cache"))
    frontdoor_summary = {
        "reachable": bool(frontdoor.get("reachable")),
        "status": _clean(frontdoor.get("status")) or "unknown",
        "model_advertised": selected_model.lower() in _models(frontdoor.get("models")),
    }

    reachable_workers = [worker for worker in eligible_workers if worker["reachable"]]
    model_workers = [
        worker for worker in reachable_workers if worker["model_advertised"]
    ]
    if cache.get("status") == "stale_error":
        reason = "mesh_probe_stale"
    elif not frontdoor_summary["reachable"]:
        reason = "local_frontdoor_unreachable"
    elif not eligible_workers:
        reason = "no_eligible_workers_configured"
    elif not reachable_workers:
        reason = "no_eligible_worker_reachable"
    elif not model_workers:
        reason = "model_not_available_on_eligible_workers"
    else:
        reason = "available"

    return {
        "schema": CAPACITY_SCHEMA,
        "available": reason == "available",
        "reason": reason,
        "requested_model": requested_model,
        "selected_model": selected_model,
        "frontdoor": frontdoor_summary,
        "eligible_workers": eligible_workers,
        "ineligible_workers": ineligible_workers,
        "cache": {
            "status": _clean(cache.get("status")) or "unknown",
            "age_seconds": _int(cache.get("age_seconds")),
            "ttl_seconds": _int(cache.get("ttl_seconds")),
        },
        "cloud_fallback": bool(ROUTE_POLICY_FALLBACKS["allow_cloud_fallback"]),
        "retryable": reason != "available",
    }
