from __future__ import annotations

import time
from typing import Any, Iterable
from urllib.parse import urlsplit

from app.services.norllama.capability_catalog import (
    catalog_models,
    model_aliases_for_catalog_item,
    runtime_model_for_catalog_item,
)
from app.services.norllama.route_outcomes import local_route_cooldown

MODEL_REALITY_SCHEMA = "norman.norllama.model-reality.v1"
HEAVY_MODEL_FALLBACK_LIMIT_B = 4
FRESH_BENCHMARK_SECONDS = 7 * 24 * 60 * 60
SERVICE_ENDPOINT_KINDS_BY_DISPATCH = {
    "ocr_proxy": {"ocr", "document_parse", "doc_parse", "vision"},
    "rerank_proxy": {"rerank", "rank"},
    "safety_proxy": {"safety", "prompt_injection", "moderation"},
    "transcribe_proxy": {"asr", "audio", "stt", "transcribe"},
    "world_proxy": {"world"},
}
SERVICE_PATH_MARKERS_BY_DISPATCH = {
    "ocr_proxy": ("ocr", "document"),
    "rerank_proxy": ("rerank", "rank"),
    "safety_proxy": ("safety", "prompt_injection", "moderation"),
    "transcribe_proxy": ("audio", "asr", "transcribe"),
    "world_proxy": ("world",),
}
SERVICE_ROW_KEYS_BY_DISPATCH = {
    "ocr_proxy": ("ocr",),
    "rerank_proxy": ("rerank",),
    "safety_proxy": ("safety",),
    "transcribe_proxy": ("transcribe", "asr"),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _as_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _model_size_b(model: str) -> float | None:
    text = _lower(model)
    import re

    matches = re.findall(r"(\d+(?:\.\d+)?)\s*b", text)
    if not matches:
        return None
    parsed: list[float] = []
    for match in matches:
        try:
            parsed.append(float(match))
        except ValueError:
            continue
    return max(parsed) if parsed else None


def _worker_id(worker: dict[str, Any]) -> str:
    return _clean(worker.get("id") or worker.get("worker_id"))


def _worker_role(worker: dict[str, Any]) -> str:
    return _lower(worker.get("role")) or "worker"


def _worker_memory_gb(worker: dict[str, Any]) -> int:
    return _as_int(worker.get("memory_gb") or worker.get("memory"))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def _model_matches(model: str, candidates: Iterable[Any]) -> bool:
    clean = _clean(model)
    return any(_clean(candidate) == clean for candidate in candidates)


def _catalog_candidate_models(model: str, catalog_item: dict[str, Any]) -> list[str]:
    if catalog_item:
        return _ordered_unique([model, *model_aliases_for_catalog_item(catalog_item)])
    return _ordered_unique([model])


def _service_model_matches(model: str, candidate: Any) -> bool:
    clean = _lower(model)
    other = _lower(candidate)
    if not clean or not other:
        return False
    tails = {clean, clean.rsplit("/", 1)[-1], clean.rsplit(":", 1)[-1]}
    candidates = {other, other.rsplit("/", 1)[-1], other.rsplit(":", 1)[-1]}
    if clean.startswith("faster-whisper:"):
        tails.add(clean.split(":", 1)[1])
    if other.startswith("faster-whisper:"):
        candidates.add(other.split(":", 1)[1])
    return bool(tails.intersection(candidates))


def _mesh_workers(mesh: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(mesh, dict):
        return []
    workers = mesh.get("workers")
    return [dict(worker) for worker in workers if isinstance(worker, dict)]


def _mesh_models(mesh: dict[str, Any] | None) -> set[str]:
    models: set[str] = set()
    if not isinstance(mesh, dict):
        return models
    for model in _list(mesh.get("models")):
        clean = _clean(model)
        if clean:
            models.add(clean)
    for worker in _mesh_workers(mesh):
        for key in ("models", "available_models", "tags"):
            for model in _list(worker.get(key)):
                clean = _clean(model)
                if clean:
                    models.add(clean)
    return models


def _active_models(mesh: dict[str, Any] | None) -> set[str]:
    models: set[str] = set()
    for worker in _mesh_workers(mesh):
        for model in _list(worker.get("active_models")) + _list(worker.get("ps")):
            clean = _clean(model)
            if clean:
                models.add(clean)
    return models


def _workers_for_model(
    workers: list[dict[str, Any]],
    model: str,
    *,
    active: bool = False,
    reachable_only: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys = ("active_models", "ps") if active else ("models", "available_models", "tags")
    for worker in workers:
        if reachable_only and not bool(worker.get("reachable")):
            continue
        if any(_model_matches(model, _list(worker.get(key))) for key in keys):
            result.append(worker)
    return result


def _workers_for_model_names(
    workers: list[dict[str, Any]],
    model_names: list[str],
    *,
    active: bool = False,
    reachable_only: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys = ("active_models", "ps") if active else ("models", "available_models", "tags")
    for worker in workers:
        if reachable_only and not bool(worker.get("reachable")):
            continue
        if any(
            _model_matches(model, _list(worker.get(key)))
            for model in model_names
            for key in keys
        ):
            result.append(worker)
    return result


def _section_endpoints(section: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    for item in _list(section.get("endpoints")):
        if isinstance(item, dict):
            endpoints.append(dict(item))
    capabilities = section.get("capabilities")
    if isinstance(capabilities, dict):
        for item in _list(capabilities.get("endpoints")):
            if isinstance(item, dict):
                endpoints.append(dict(item))
    return endpoints


def _section_contracts(section: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for key in ("contracts", "capability_contracts"):
        for item in _list(section.get(key)):
            if isinstance(item, dict):
                contracts.append(dict(item))
    capabilities = section.get("capabilities")
    if isinstance(capabilities, dict):
        for key in ("contracts", "capability_contracts"):
            for item in _list(capabilities.get(key)):
                if isinstance(item, dict):
                    contracts.append(dict(item))
    return contracts


def _section_service_rows(
    section: dict[str, Any],
    dispatch: str,
) -> list[dict[str, str]]:
    service_keys = SERVICE_ROW_KEYS_BY_DISPATCH.get(dispatch, ())
    if not service_keys:
        return []
    rows: list[dict[str, str]] = []

    def add_row(model: Any, base_url: Any = "") -> None:
        clean_model = _clean(model)
        if not clean_model:
            return
        clean_base = _clean(base_url)
        row = {"model": clean_model, "base_url": clean_base}
        if row not in rows:
            rows.append(row)

    overview = section.get("overview")
    if isinstance(overview, dict):
        for row in _list(overview.get("fleet")):
            if not isinstance(row, dict):
                continue
            for key in service_keys:
                service = row.get(key)
                if isinstance(service, dict):
                    add_row(
                        service.get("model"),
                        service.get("base_url") or row.get("base_url"),
                    )
    downstreams = section.get("downstreams")
    if isinstance(downstreams, dict):
        for key in service_keys:
            value = downstreams.get(key)
            for row in _list(value):
                if isinstance(row, dict):
                    add_row(row.get("model"), row.get("base_url"))
            if isinstance(value, dict):
                add_row(value.get("model"), value.get("base_url"))
    for key in service_keys:
        value = section.get(key)
        if isinstance(value, dict):
            add_row(value.get("model"), value.get("base_url"))
    return rows


def _section_service_models(section: dict[str, Any], dispatch: str) -> list[str]:
    models: list[str] = []
    for row in _section_service_rows(section, dispatch):
        model = _clean(row.get("model"))
        if model and model not in models:
            models.append(model)
    return models


def _url_host(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        return _lower(urlsplit(raw).hostname)
    except ValueError:
        return ""


def _section_hosts(section: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for key in ("base_url", "public_base_url", "endpoint", "public_endpoint"):
        host = _url_host(section.get(key))
        if host:
            hosts.add(host)
    return hosts


def _worker_ids_by_host(mesh: dict[str, Any] | None) -> dict[str, str]:
    hosts: dict[str, str] = {}
    for worker in _mesh_workers(mesh):
        worker_id = _worker_id(worker)
        if not worker_id or not worker.get("reachable"):
            continue
        for host in _section_hosts(worker):
            hosts.setdefault(host, worker_id)
    return hosts


def _service_row_is_local_to_section(
    section: dict[str, Any],
    row: dict[str, str],
) -> bool:
    base_host = _url_host(row.get("base_url"))
    if not base_host:
        return True
    if base_host in {"127.0.0.1", "::1", "localhost"}:
        return True
    return base_host in _section_hosts(section)


def _mesh_sections(mesh: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(mesh, dict):
        return []
    sections: list[tuple[str, dict[str, Any]]] = []
    frontdoor = mesh.get("frontdoor")
    if isinstance(frontdoor, dict):
        sections.append(("frontdoor", frontdoor))
    for worker in _mesh_workers(mesh):
        worker_id = _worker_id(worker)
        sections.append((worker_id or "worker", worker))
    return sections


def _endpoint_matches_dispatch(endpoint: dict[str, Any], dispatch: str) -> bool:
    kinds = SERVICE_ENDPOINT_KINDS_BY_DISPATCH.get(dispatch, set())
    markers = SERVICE_PATH_MARKERS_BY_DISPATCH.get(dispatch, ())
    kind = _lower(endpoint.get("kind") or endpoint.get("type"))
    path = _lower(endpoint.get("path") or endpoint.get("url"))
    if kind and kind in kinds:
        return True
    return bool(path and any(marker in path for marker in markers))


def _contract_matches_catalog(
    contract: dict[str, Any],
    *,
    model: str,
    dispatch: str,
) -> bool:
    if _lower(contract.get("dispatch")) == dispatch:
        return _clean(contract.get("default_model")) == model
    return _clean(contract.get("default_model")) == model


def service_evidence_for_catalog_item(
    mesh: dict[str, Any] | None,
    catalog_item: dict[str, Any],
) -> dict[str, Any]:
    """Return live service evidence for non-Ollama catalog lanes.

    Service lanes such as faster-whisper ASR are not required to appear in
    /api/tags. They still need endpoint or contract evidence, worker attribution,
    and benchmark proof before they become default routes.
    """

    model = _clean(catalog_item.get("model"))
    dispatch = _lower(catalog_item.get("dispatch"))
    desired_residency = _lower(catalog_item.get("residency"))
    target_worker = _clean(catalog_item.get("target_worker"))
    if not model or not dispatch:
        return {
            "installed": False,
            "servable": False,
            "resident": False,
            "worker_ids": [],
            "endpoints": [],
            "contracts": [],
            "reason": "",
        }
    if (
        desired_residency != "service"
        and dispatch not in SERVICE_ENDPOINT_KINDS_BY_DISPATCH
    ):
        return {
            "installed": False,
            "servable": False,
            "resident": False,
            "worker_ids": [],
            "endpoints": [],
            "contracts": [],
            "reason": "",
        }
    endpoints: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    service_models_seen: list[str] = []
    worker_ids: list[str] = []
    host_worker_ids = _worker_ids_by_host(mesh)
    frontdoor_only = False
    for section_id, section in _mesh_sections(mesh):
        section_reachable = bool(section.get("reachable"))
        matched_endpoint = [
            endpoint
            for endpoint in _section_endpoints(section)
            if _endpoint_matches_dispatch(endpoint, dispatch)
        ]
        matched_contract = [
            contract
            for contract in _section_contracts(section)
            if _contract_matches_catalog(contract, model=model, dispatch=dispatch)
        ]
        service_rows = _section_service_rows(section, dispatch)
        service_models = [_clean(row.get("model")) for row in service_rows]
        for service_model in service_models:
            if service_model not in service_models_seen:
                service_models_seen.append(service_model)
        matching_service_rows = [
            row
            for row in service_rows
            if _service_model_matches(model, row.get("model"))
        ]
        model_matches_service = bool(matching_service_rows or matched_contract)
        if not matched_endpoint and not matched_contract:
            continue
        endpoints.extend(matched_endpoint)
        contracts.extend(matched_contract)
        if not matched_endpoint or not model_matches_service:
            continue
        attributed_ids: list[str] = []
        for row in matching_service_rows:
            if section_id != "frontdoor" and _service_row_is_local_to_section(
                section, row
            ):
                attributed_ids.append(section_id)
                continue
            host_worker_id = host_worker_ids.get(_url_host(row.get("base_url")))
            if host_worker_id:
                attributed_ids.append(host_worker_id)
        if not matching_service_rows and matched_contract and section_id != "frontdoor":
            attributed_ids.append(section_id)
        if section_id == "frontdoor":
            frontdoor_only = True
        if not section_reachable and section_id != "frontdoor":
            continue
        for attributed_id in attributed_ids:
            if attributed_id and attributed_id not in worker_ids:
                worker_ids.append(attributed_id)
    target_workers = [
        item.strip()
        for part in target_worker.split("|")
        for item in part.split(",")
        if item.strip()
    ]
    target_matches = not target_workers or any(
        worker in worker_ids for worker in target_workers
    )
    if frontdoor_only and not worker_ids and target_worker:
        target_matches = False
    installed = bool((worker_ids or frontdoor_only) and target_matches)
    return {
        "installed": installed,
        "servable": installed,
        "resident": bool(installed and desired_residency == "service"),
        "worker_ids": worker_ids,
        "endpoints": endpoints[:8],
        "contracts": contracts[:8],
        "service_models": service_models_seen[:8],
        "frontdoor_only": frontdoor_only and not worker_ids,
        "target_matches": target_matches,
        "reason": "service endpoint advertised"
        if installed
        else "service endpoint not advertised by target worker",
    }


def _benchmark_by_model(
    items: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        model = _clean(item.get("model"))
        if model and model not in result:
            result[model] = dict(item)
    return result


def _benchmark_fresh(packet_meta: dict[str, Any] | None, *, now: int) -> bool:
    if not isinstance(packet_meta, dict):
        return False
    generated_at = _clean(packet_meta.get("generated_at"))
    if not generated_at:
        return False
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        age = now - int(parsed.timestamp())
    except (TypeError, ValueError):
        return False
    return age <= FRESH_BENCHMARK_SECONDS


def _benchmark_evidence(item: dict[str, Any]) -> dict[str, Any]:
    quality = item.get("benchmark_quality")
    if not isinstance(quality, dict):
        quality = {}
    source = _clean(item.get("source"))
    score = _as_float(quality.get("score"))
    if score is None:
        score = _as_float(item.get("score"))
    coverage = _as_float(quality.get("coverage_ratio"))
    if coverage is None:
        coverage = _as_float(item.get("coverage_ratio"))
    state = _clean(quality.get("state") or item.get("benchmark_status"))
    benchmarked = source == "uplink_benchmark" and (
        bool(state) or score is not None or coverage is not None
    )
    eligible = bool(quality.get("eligible")) if quality else benchmarked
    return {
        "source": source,
        "state": state,
        "benchmarked": benchmarked,
        "eligible": eligible,
        "score": score,
        "coverage_ratio": coverage,
        "fresh": False,
    }


def _worker_fit(
    *,
    model: str,
    target_worker_id: str,
    workers: list[dict[str, Any]],
    desired_residency: str,
) -> dict[str, Any]:
    size_b = _model_size_b(model)
    worker = next(
        (worker for worker in workers if _worker_id(worker) == target_worker_id),
        {},
    )
    memory_gb = _worker_memory_gb(worker)
    role = _worker_role(worker)
    reasons: list[str] = []
    ok = True
    if (
        role == "fallback"
        and size_b is not None
        and size_b > HEAVY_MODEL_FALLBACK_LIMIT_B
    ):
        ok = False
        reasons.append("heavy model cannot be warmed on fallback node")
    if memory_gb and size_b is not None and size_b > max(1, memory_gb * 0.75):
        ok = False
        reasons.append("model size exceeds conservative worker memory fit")
    if desired_residency in {"cold_only", "lab"}:
        ok = False
        reasons.append("catalog marks model as cold/lab only")
    return {
        "ok": ok,
        "model_size_b": size_b,
        "worker_id": target_worker_id,
        "worker_role": role,
        "worker_memory_gb": memory_gb,
        "reasons": reasons,
    }


def _state(
    *,
    catalog_present: bool,
    installed: bool,
    servable: bool,
    benchmarked: bool,
    benchmark_eligible: bool,
    resident: bool,
    cooldown: dict[str, Any],
    worker_fit_ok: bool,
) -> tuple[str, str, bool, bool]:
    if cooldown.get("active"):
        return "degraded", "cooldown", False, False
    if not catalog_present and not installed:
        return "aspirational", "unknown", False, False
    if not installed:
        return "aspirational", "catalog_only", False, False
    if not servable:
        return "installed", "installed_unserved", False, False
    if not benchmarked:
        return "servable", "installed_unproven", False, False
    if not benchmark_eligible:
        return "blocked", "benchmark_blocked", False, False
    if not worker_fit_ok:
        return "blocked", "worker_fit_blocked", False, False
    if resident:
        return "resident", "ready", True, True
    return "routable", "ready", True, True


def build_model_reality(
    *,
    mesh: dict[str, Any] | None = None,
    benchmark_items: list[dict[str, Any]] | None = None,
    route_outcomes: list[dict[str, Any]] | None = None,
    packet_meta: dict[str, Any] | None = None,
    cooldown_seconds: int = 900,
    now: int | None = None,
) -> dict[str, Any]:
    """Reconcile desired catalog state with live inventory and benchmark proof."""

    current = int(now if now is not None else time.time())
    workers = _mesh_workers(mesh)
    mesh_model_set = _mesh_models(mesh)
    active_model_set = _active_models(mesh)
    catalog: dict[str, dict[str, Any]] = {}
    for item in catalog_models():
        for alias in model_aliases_for_catalog_item(item):
            catalog.setdefault(alias, dict(item))
    benchmark = _benchmark_by_model(benchmark_items)
    models = sorted(
        model for model in set(catalog) | set(benchmark) | mesh_model_set if model
    )
    fresh = _benchmark_fresh(packet_meta, now=current)
    rows: list[dict[str, Any]] = []
    for model in models:
        catalog_item = catalog.get(model, {})
        candidate_models = _catalog_candidate_models(model, catalog_item)
        benchmark_item = benchmark.get(model, {})
        if not benchmark_item:
            benchmark_item = next(
                (benchmark[name] for name in candidate_models if name in benchmark),
                {},
            )
        target_worker = _clean(
            benchmark_item.get("target_worker") or catalog_item.get("target_worker")
        )
        desired_residency = _clean(
            benchmark_item.get("residency") or catalog_item.get("residency")
        )
        fit_model = (
            runtime_model_for_catalog_item(catalog_item) if catalog_item else model
        )
        service = service_evidence_for_catalog_item(mesh, catalog_item)
        installed = bool(
            any(candidate in mesh_model_set for candidate in candidate_models)
            or service.get("installed")
        )
        model_workers = _workers_for_model_names(workers, candidate_models)
        healthy_workers = _workers_for_model_names(
            workers, candidate_models, reachable_only=True
        )
        active_workers = _workers_for_model_names(
            workers, candidate_models, active=True
        )
        if service.get("installed"):
            service_worker_ids = set(service.get("worker_ids") or [])
            service_workers = [
                worker for worker in workers if _worker_id(worker) in service_worker_ids
            ]
            if not model_workers:
                model_workers = service_workers
            if not healthy_workers:
                healthy_workers = [
                    worker for worker in service_workers if worker.get("reachable")
                ]
        if not target_worker and healthy_workers:
            target_worker = _worker_id(healthy_workers[0])
        benchmark_evidence = _benchmark_evidence(benchmark_item)
        benchmark_evidence["fresh"] = fresh and benchmark_evidence["benchmarked"]
        cooldown = local_route_cooldown(
            route_outcomes or [],
            model=model,
            worker_id=target_worker,
            cooldown_seconds=cooldown_seconds,
            now=current,
        )
        fit = _worker_fit(
            model=fit_model,
            target_worker_id=target_worker,
            workers=workers,
            desired_residency=desired_residency,
        )
        resident = bool(
            any(candidate in active_model_set for candidate in candidate_models)
            or active_workers
            or service.get("resident")
        )
        state, proof_status, route_eligible, warm_eligible = _state(
            catalog_present=model in catalog,
            installed=installed,
            servable=bool(healthy_workers) or bool(service.get("servable")),
            benchmarked=bool(benchmark_evidence["fresh"]),
            benchmark_eligible=bool(benchmark_evidence["eligible"]),
            resident=resident,
            cooldown=cooldown,
            worker_fit_ok=bool(fit.get("ok")),
        )
        row = {
            "schema": "norman.norllama.model-reality.row.v1",
            "model": model,
            "desired_model": _clean(catalog_item.get("model")),
            "runtime_model": fit_model,
            "model_aliases": candidate_models,
            "state": state,
            "proof_status": proof_status,
            "catalog_present": model in catalog,
            "installed": installed,
            "servable": bool(healthy_workers) or bool(service.get("servable")),
            "benchmarked": bool(benchmark_evidence["fresh"]),
            "routable": route_eligible,
            "resident": resident,
            "degraded": state == "degraded",
            "blocked": state == "blocked",
            "route_eligible": route_eligible,
            "warm_residency_eligible": warm_eligible,
            "worker_fit": bool(fit.get("ok")),
            "cold_start_ok": proof_status == "ready",
            "memory_pressure_ok": bool(fit.get("ok")),
            "desired_residency": desired_residency,
            "target_worker": target_worker,
            "target_role": _clean(
                benchmark_item.get("target_role") or catalog_item.get("target_role")
            ),
            "workers": [
                _worker_id(worker) for worker in model_workers if _worker_id(worker)
            ],
            "healthy_workers": [
                _worker_id(worker) for worker in healthy_workers if _worker_id(worker)
            ],
            "active_workers": [
                _worker_id(worker) for worker in active_workers if _worker_id(worker)
            ],
            "benchmark": benchmark_evidence,
            "cooldown": cooldown,
            "fit": fit,
            "service": service,
            "reasons": [
                reason
                for reason in [
                    "catalog model is not in live Norllama inventory"
                    if model in catalog and not installed and not service.get("reason")
                    else "",
                    _clean(service.get("reason"))
                    if model in catalog
                    and service.get("reason")
                    and not service.get("installed")
                    else "",
                    "model is installed but lacks fresh Uplink benchmark evidence"
                    if installed and not benchmark_evidence["fresh"]
                    else "",
                    "recent route failure is cooling this model down"
                    if cooldown.get("active")
                    else "",
                    *list(fit.get("reasons") or []),
                ]
                if reason
            ],
        }
        rows.append(row)
    by_state: dict[str, int] = {}
    for row in rows:
        state = _clean(row.get("state")) or "unknown"
        by_state[state] = by_state.get(state, 0) + 1
    return {
        "schema": MODEL_REALITY_SCHEMA,
        "model_count": len(rows),
        "route_eligible_count": sum(1 for row in rows if row["route_eligible"]),
        "warm_residency_eligible_count": sum(
            1 for row in rows if row["warm_residency_eligible"]
        ),
        "by_state": by_state,
        "benchmark_fresh": fresh,
        "cooldown_seconds": max(0, int(cooldown_seconds or 0)),
        "models": rows,
        "by_model": {row["model"]: row for row in rows},
        "checked_at": current,
    }
