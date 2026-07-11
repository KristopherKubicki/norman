from __future__ import annotations

from typing import Any

from app.services.norllama.specialist_lanes import summarize_specialist_cascade
from app.services.norllama.types import NorllamaReceipt


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, NorllamaReceipt):
        return value.as_dict()
    if hasattr(value, "as_dict") and callable(value.as_dict):
        payload = value.as_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _unique_clean(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean(value)
        if text and text not in result:
            result.append(text)
    return result


def planner_receipt_artifacts(
    receipt: NorllamaReceipt | dict[str, Any],
    artifacts: list[str] | None = None,
) -> list[str]:
    payload = _as_dict(receipt)
    evidence_paths = payload.get("evidence_paths")
    return _unique_clean(
        list(evidence_paths if isinstance(evidence_paths, list) else [])
        + list(artifacts or [])
    )


def planner_receipt_payload(
    receipt: NorllamaReceipt | dict[str, Any],
    *,
    capabilities: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    receipt_payload = _as_dict(receipt)
    route = (
        dict(receipt_payload.get("route"))
        if isinstance(receipt_payload.get("route"), dict)
        else {}
    )
    route_receipt = (
        dict(receipt_payload.get("route_receipt"))
        if isinstance(receipt_payload.get("route_receipt"), dict)
        else {}
    )
    specialist_cascade = (
        dict(route_receipt.get("specialist_cascade"))
        if isinstance(route_receipt.get("specialist_cascade"), dict)
        else {}
    )
    specialist_summary = (
        summarize_specialist_cascade(specialist_cascade) if specialist_cascade else {}
    )
    return {
        "receipt": receipt_payload,
        "route_receipt": route_receipt,
        "specialist_cascade": specialist_cascade,
        "specialist_summary": specialist_summary,
        "route": route,
        "provider": _clean(route.get("provider")),
        "selected_provider": _clean(route_receipt.get("selected_provider"))
        or _clean(route.get("provider")),
        "selected_model": _clean(route_receipt.get("selected_model"))
        or _clean(route.get("model")),
        "selected_worker_id": _clean(route_receipt.get("selected_worker")),
        "usage_bucket": _clean(route_receipt.get("usage_bucket")),
        "cloud_proxy": bool(
            route_receipt.get("cloud_proxy") or route.get("cloud_proxy")
        ),
        "output_shape": _clean(route_receipt.get("output_shape")),
        "verifier_result": _clean(route_receipt.get("verifier_result")),
        "capability": _clean(route.get("capability")),
        "task_kind": _clean(receipt_payload.get("task_kind")),
        "status": _clean(receipt_payload.get("status")) or "planned",
        "capabilities": dict(capabilities or {}),
        "artifacts": planner_receipt_artifacts(receipt_payload, artifacts),
        "metadata": dict(metadata or {}),
    }


def planner_receipt_summary(receipt: NorllamaReceipt | dict[str, Any]) -> str:
    payload = _as_dict(receipt)
    route = (
        dict(payload.get("route") or {})
        if isinstance(payload.get("route"), dict)
        else {}
    )
    kind = _clean(payload.get("task_kind")) or "task"
    provider = _clean(route.get("provider")) or "norllama"
    capability = _clean(route.get("capability")) or kind
    status = _clean(payload.get("status")) or "planned"
    return f"Planner receipt {status}: {kind} via {provider}/{capability}"
