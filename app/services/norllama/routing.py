from __future__ import annotations

import ipaddress
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings
from app.services.norllama.capability_catalog import default_model_for_task_kind
from app.services.norllama.specialist_lanes import (
    evaluate_specialist_cascade,
    specialist_cascade_template,
)
from app.services.norllama.warm_policy import select_model_for_task_kind
from app.services.norllama.route_policy import route_policy_contract
from app.services.norllama.route_policy_artifact import authorize_route_under_policy
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskKind,
    NorllamaTaskRequest,
)

NORLLAMA_PROVIDER_ALIASES = {"norllama", "ollama", "local_ollama", "local-ollama"}
OPENAI_COMPATIBLE_PROVIDERS = {"openai_compatible", "openai-compatible"}
CLOUD_PROXY_PROVIDERS = {
    "aws-bedrock",
    "bedrock",
    "codex",
    "openai",
    "openai-direct",
    *OPENAI_COMPATIBLE_PROVIDERS,
}
TOOL_TASK_KINDS = {
    NorllamaTaskKind.OCR,
    NorllamaTaskKind.DOC_PARSE,
    NorllamaTaskKind.STT,
    NorllamaTaskKind.ASR,
    NorllamaTaskKind.TTS,
    NorllamaTaskKind.EMBED,
    NorllamaTaskKind.RERANK,
    NorllamaTaskKind.SAFETY,
    NorllamaTaskKind.PROMPT_INJECTION,
    NorllamaTaskKind.GUI_GROUND,
    NorllamaTaskKind.FORECAST,
    NorllamaTaskKind.GRAPH,
    NorllamaTaskKind.NETWORK,
    NorllamaTaskKind.WORLD,
}
TOOL_TASK_KIND_VALUES = {kind.value for kind in TOOL_TASK_KINDS}

_CAPABILITY_BY_KIND = {
    NorllamaTaskKind.CHAT: "text_chat",
    NorllamaTaskKind.CODE: "code",
    NorllamaTaskKind.SCOUT: "scout",
    NorllamaTaskKind.PLAN: "planner",
    NorllamaTaskKind.FILTER: "filter",
    NorllamaTaskKind.SUMMARIZE: "summarizer",
    NorllamaTaskKind.COMPACT: "context_compactor",
    NorllamaTaskKind.VERIFY: "verifier",
    NorllamaTaskKind.JUDGE: "judge",
    NorllamaTaskKind.OCR: "ocr",
    NorllamaTaskKind.DOC_PARSE: "doc_parse",
    NorllamaTaskKind.STT: "stt",
    NorllamaTaskKind.ASR: "asr",
    NorllamaTaskKind.TTS: "tts",
    NorllamaTaskKind.EMBED: "embedding",
    NorllamaTaskKind.RERANK: "rerank",
    NorllamaTaskKind.SAFETY: "safety",
    NorllamaTaskKind.PROMPT_INJECTION: "prompt_injection",
    NorllamaTaskKind.GUI_GROUND: "gui_ground",
    NorllamaTaskKind.FORECAST: "forecast",
    NorllamaTaskKind.GRAPH: "graph",
    NorllamaTaskKind.NETWORK: "network",
    NorllamaTaskKind.WORLD: "world",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        clean = _clean(item)
        if clean and clean not in result:
            result.append(clean)
    return result


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    clean = _lower(value)
    if not clean:
        return default
    if clean in {"1", "true", "yes", "on", "enabled", "force"}:
        return True
    if clean in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _task_kind_value(task_kind: NorllamaTaskKind | str | None) -> str:
    if isinstance(task_kind, NorllamaTaskKind):
        return task_kind.value
    return _clean(task_kind).lower()


def _route_policy_value(policy: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(policy.get(key))
        if value:
            return value
    return ""


def _route_policy_artifact(policy: dict[str, Any]) -> dict[str, Any]:
    artifact = policy.get("route_policy_artifact")
    if isinstance(artifact, dict) and artifact:
        return artifact
    return route_policy_contract()


def _route_policy_authorization(
    policy: dict[str, Any],
    *,
    execution_mode: str,
    provider: str,
    model: str = "",
    lane: str = "",
) -> dict[str, Any]:
    manual = policy.get("manual_degraded_authorization")
    return authorize_route_under_policy(
        policy_artifact=_route_policy_artifact(policy),
        execution_mode=execution_mode,
        requested_provider=provider,
        requested_model=model,
        requested_lane=lane,
        manual_degraded_authorization=manual if isinstance(manual, dict) else None,
    )


def _normalize_provider(provider: str) -> str:
    normalized = _lower(provider)
    if normalized in {"aws_bedrock", "awsbedrock"}:
        return "aws-bedrock"
    if normalized in {"openai_direct", "openai-direct"}:
        return "openai-direct"
    return normalized


def _public_endpoint(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.split("?", 1)[0]
    if not parsed.netloc:
        return raw.split("?", 1)[0]
    netloc = (parsed.hostname or parsed.netloc.rsplit("@", 1)[-1]).lower()
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", ""))


def _endpoint_key(value: Any) -> str:
    public = _public_endpoint(value)
    if not public:
        return ""
    try:
        parsed = urlsplit(public)
    except ValueError:
        return public.lower().rstrip("/")
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return public.lower().rstrip("/")
    if parsed.port:
        return f"{host}:{parsed.port}"
    if parsed.scheme == "https":
        return f"{host}:443"
    if parsed.scheme == "http":
        return f"{host}:80"
    return host


def _worker_roster() -> list[dict[str, Any]]:
    workers: list[dict[str, Any]] = []
    for index, item in enumerate(
        getattr(settings, "llm_mesh_workers", []) or [], start=1
    ):
        if not isinstance(item, dict):
            continue
        worker_id = _clean(item.get("id") or item.get("worker_id")) or f"worker-{index}"
        base_url = _public_endpoint(
            item.get("base_url") or item.get("endpoint") or item.get("url")
        )
        workers.append(
            {
                "id": worker_id,
                "name": _clean(item.get("name")) or worker_id,
                "role": _clean(item.get("role")) or "worker",
                "base_url": base_url,
                "endpoint_key": _endpoint_key(base_url),
                "memory_gb": item.get("memory_gb"),
                "priority": item.get("priority", index),
            }
        )
    return workers


def _worker_by_id(worker_id: str) -> dict[str, Any]:
    clean = _clean(worker_id)
    if not clean:
        return {}
    compact = clean.replace("-", "").replace("_", "").lower()
    for worker in _worker_roster():
        worker_id_value = _clean(worker["id"])
        worker_compact = worker_id_value.replace("-", "").replace("_", "").lower()
        if worker_id_value == clean or worker_compact == compact:
            return worker
    return {}


def _worker_by_endpoint(endpoint: str) -> dict[str, Any]:
    key = _endpoint_key(endpoint)
    if not key:
        return {}
    for worker in _worker_roster():
        if worker.get("endpoint_key") == key:
            return worker
    return {}


def _worker_label_for_endpoint(endpoint: str) -> str:
    worker = _worker_by_endpoint(endpoint)
    if worker:
        return _clean(worker.get("id"))
    return _public_endpoint(endpoint)


def _worker_label_for_value(value: str) -> str:
    clean = _clean(value)
    if not clean:
        return ""
    if "://" in clean:
        return _worker_label_for_endpoint(clean)
    worker = _worker_by_id(clean)
    if worker:
        return _clean(worker.get("id"))
    return clean


def _policy_worker(policy: dict[str, Any]) -> dict[str, Any]:
    worker_id = _route_policy_value(
        policy,
        "selected_worker_id",
        "worker_id",
        "norllama_worker_id",
        "preferred_worker_id",
    )
    return _worker_by_id(worker_id) if worker_id else {}


def _frontdoor_matches(endpoint: str) -> bool:
    route_key = _endpoint_key(endpoint)
    frontdoor_key = _endpoint_key(getattr(settings, "llm_offline_base_url", ""))
    return bool(route_key and frontdoor_key and route_key == frontdoor_key)


def _endpoint_is_lan(endpoint: str) -> bool:
    public = _public_endpoint(endpoint)
    if not public:
        return False
    try:
        parsed = urlsplit(public if "://" in public else f"//{public}")
    except ValueError:
        return False
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return False
    if host in {"localhost", "llm.home.arpa"} or host.endswith(".home.arpa"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _endpoint_is_local_frontdoor(endpoint: str) -> bool:
    return _frontdoor_matches(endpoint) or _endpoint_is_lan(endpoint)


def _route_endpoint(
    policy: dict[str, Any],
    provider: str,
    *,
    offline_slot: bool = False,
) -> str:
    endpoint = _route_policy_value(policy, "endpoint", "base_url")
    if endpoint:
        return endpoint
    if offline_slot or provider in NORLLAMA_PROVIDER_ALIASES:
        return _clean(getattr(settings, "llm_offline_base_url", ""))
    return _default_endpoint(provider)


def _route_model(
    policy: dict[str, Any],
    provider: str,
    *,
    offline_slot: bool = False,
    task_kind: NorllamaTaskKind | str | None = None,
) -> str:
    return _clean(
        _route_model_selection(
            policy,
            provider,
            offline_slot=offline_slot,
            task_kind=task_kind,
        ).get("model")
    )


def _route_model_selection(
    policy: dict[str, Any],
    provider: str,
    *,
    offline_slot: bool = False,
    task_kind: NorllamaTaskKind | str | None = None,
) -> dict[str, Any]:
    model = _route_policy_value(policy, "model", "preferred_model")
    authorization = _route_policy_authorization(
        policy,
        execution_mode="model_selection",
        provider=provider,
        model=model,
        lane=_route_policy_value(policy, "lane", "preferred_lane")
        or _task_kind_value(task_kind),
    )
    if not authorization.get("allowed"):
        return {
            "schema": "norman.norllama.model-selection.v1",
            "selected": False,
            "model": "",
            "source": "route_policy_blocked",
            "reason": _clean(authorization.get("reason"))
            or "route policy blocked model selection",
            "policy_authorization": authorization,
            "production_route_eligible": False,
        }
    explicit_lock = any(
        _flag(policy.get(key))
        for key in (
            "route_lock",
            "strict_route",
            "operator_model_override",
            "operator_route_lock",
        )
    )
    if explicit_lock and model:
        return {
            "schema": "norman.norllama.model-selection.v1",
            "selected": True,
            "model": model,
            "source": "explicit_route_lock",
            "reason": "explicit operator route lock",
            "production_route_eligible": False,
            "capability_route_state": "manual_route_lock",
            "promotion_authoritative": False,
        }
    model_selection = _clean(policy.get("model_selection")).lower()
    if model_selection in {
        "warm_policy",
        "benchmark_policy",
        "benchmark",
        "warm",
        "benchmark_warm_policy",
    }:
        recent_outcomes = policy.get("recent_route_outcomes") or policy.get(
            "route_outcomes"
        )
        selection = select_model_for_task_kind(
            _task_kind_value(task_kind),
            policy=policy,
            route_outcomes=recent_outcomes if isinstance(recent_outcomes, list) else [],
        )
        if selection.get("selected") and _clean(selection.get("model")):
            return {
                **selection,
                "schema": "norman.norllama.model-selection.v1",
                "model": _clean(selection.get("model")),
                "source": "warm_policy",
            }
        if model:
            return {
                **selection,
                "schema": "norman.norllama.model-selection.v1",
                "selected": True,
                "model": model,
                "source": "explicit_model_unproven",
                "reason": (
                    _clean(selection.get("reason"))
                    or "warm-policy did not select; explicit model fallback"
                ),
                "fallback_used": True,
                "fallback_reason": (
                    _clean(selection.get("reason"))
                    or "warm-policy did not select; explicit model fallback"
                ),
            }
        return {
            **selection,
            "schema": "norman.norllama.model-selection.v1",
            "selected": False,
            "model": "",
            "source": "warm_policy",
        }
    if model:
        return {
            "schema": "norman.norllama.model-selection.v1",
            "selected": True,
            "model": model,
            "source": "explicit_model",
            "reason": "explicit model from route policy",
        }
    use_catalog = _flag(policy.get("use_capability_catalog")) or model_selection in {
        "capability_catalog",
        "catalog",
        "benchmark_catalog",
    }
    if use_catalog or _flag(policy.get("prefer_capability_model")):
        catalog_model = default_model_for_task_kind(_task_kind_value(task_kind))
        if catalog_model:
            return {
                "schema": "norman.norllama.model-selection.v1",
                "selected": True,
                "model": catalog_model,
                "source": "capability_catalog",
                "reason": "explicit capability catalog selection",
            }
    if _task_kind_value(task_kind) in TOOL_TASK_KIND_VALUES:
        catalog_model = default_model_for_task_kind(_task_kind_value(task_kind))
        if catalog_model:
            return {
                "schema": "norman.norllama.model-selection.v1",
                "selected": True,
                "model": catalog_model,
                "source": "capability_catalog",
                "reason": "default specialist lane model",
            }
    if offline_slot or provider in NORLLAMA_PROVIDER_ALIASES:
        configured = _clean(getattr(settings, "llm_offline_model", ""))
        if configured:
            return {
                "schema": "norman.norllama.model-selection.v1",
                "selected": True,
                "model": configured,
                "source": "offline_default",
                "reason": "configured offline model",
            }
        catalog_model = default_model_for_task_kind(_task_kind_value(task_kind))
        return {
            "schema": "norman.norllama.model-selection.v1",
            "selected": bool(catalog_model),
            "model": catalog_model,
            "source": "offline_catalog_fallback",
            "reason": "offline fallback model",
        }
    default_model = _default_model(provider)
    return {
        "schema": "norman.norllama.model-selection.v1",
        "selected": bool(default_model),
        "model": default_model,
        "source": "provider_default",
        "reason": "provider default model",
    }


def _base_attribution(
    *,
    provider: str,
    endpoint: str,
    policy: dict[str, Any],
    cloud_proxy: bool,
) -> dict[str, Any]:
    public_endpoint = _public_endpoint(endpoint)
    authorization = _route_policy_authorization(
        policy,
        execution_mode="route_attribution",
        provider=provider,
        model=_route_policy_value(policy, "model", "preferred_model"),
        lane=_route_policy_value(policy, "lane", "preferred_lane"),
    )
    explicit_worker = _policy_worker(policy)
    direct_worker = _worker_by_endpoint(public_endpoint)
    peer_path = _clean_list(
        policy.get("peer_path")
        or policy.get("selected_peer_path")
        or policy.get("norllama_peer_path")
    )
    frontdoor = _frontdoor_matches(public_endpoint) and not direct_worker

    if cloud_proxy:
        source = "cloud_proxy"
        scope = "cloud_proxy"
        exact_worker = False
        worker = explicit_worker
    elif direct_worker:
        source = "configured_worker_endpoint"
        scope = "direct_worker"
        exact_worker = True
        worker = direct_worker
    elif explicit_worker:
        source = "policy_worker"
        scope = "policy_worker"
        exact_worker = True
        worker = explicit_worker
    elif frontdoor:
        source = "frontdoor_delegated"
        scope = "frontdoor"
        exact_worker = False
        worker = {}
    else:
        source = "endpoint_unmapped" if public_endpoint else "route_unmapped"
        scope = "local_endpoint" if public_endpoint else "unknown"
        exact_worker = False
        worker = {}

    return {
        "schema": "norman.norllama.route-attribution.v1",
        "provider": provider,
        "routing_scope": scope,
        "selection_source": source,
        "endpoint": public_endpoint,
        "endpoint_key": _endpoint_key(public_endpoint),
        "frontdoor": frontdoor,
        "exact_worker": exact_worker,
        "worker_id": worker.get("id", ""),
        "target_worker_id": worker.get("id", ""),
        "worker_name": worker.get("name", ""),
        "worker_role": worker.get("role", ""),
        "worker_endpoint": worker.get("base_url", ""),
        "worker_memory_gb": worker.get("memory_gb"),
        "gateway_selected_worker": "",
        "observed_worker": "",
        "observed_worker_source": "",
        "route_policy_authorization": authorization,
        "policy_id": authorization.get("policy_id", ""),
        "policy_hash": authorization.get("policy_hash", ""),
        "policy_lifecycle_state": authorization.get("lifecycle_state", ""),
        "peer_path": peer_path,
        "attempts": [],
    }


def _response_field(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    for container_key in (
        "route",
        "routing",
        "norllama",
        "norllama_route",
        "attribution",
    ):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            for key in keys:
                if key in nested:
                    return nested.get(key)
    return ""


def _headers(payload: dict[str, Any]) -> dict[str, Any]:
    headers = payload.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {str(key).lower(): value for key, value in headers.items()}


def _gateway_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested gateway receipt fragment when a proxy emits one."""

    if not isinstance(payload, dict):
        return {}
    for value in (
        payload.get("norllama"),
        payload.get("routing"),
        payload.get("route"),
    ):
        if isinstance(value, dict):
            return value
    raw = payload.get("raw")
    if isinstance(raw, dict):
        for value in (raw.get("norllama"), raw.get("routing"), raw.get("route")):
            if isinstance(value, dict):
                return value
    return {}


def with_response_attribution(
    route: NorllamaRoute,
    payload: dict[str, Any] | None,
) -> NorllamaRoute:
    """Refine a route with worker/peer details returned by the gateway."""

    if not isinstance(payload, dict):
        return route
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    headers = _headers(payload)
    worker_id = _clean(
        headers.get("x-norllama-worker-id")
        or headers.get("x-norllama-worker")
        or _response_field(
            payload, "worker_id", "selected_worker_id", "selected_worker"
        )
        or _response_field(raw, "worker_id", "selected_worker_id", "selected_worker")
    )
    worker_endpoint = _clean(
        headers.get("x-norllama-worker-endpoint")
        or headers.get("x-norllama-upstream")
        or _response_field(payload, "upstream", "upstream_url", "worker_endpoint")
        or _response_field(raw, "upstream", "upstream_url", "worker_endpoint")
    )
    peer_path = _clean_list(
        headers.get("x-norllama-peer-path")
        or headers.get("x-norllama-peer")
        or _response_field(payload, "peer_path", "selected_peer_path")
        or _response_field(raw, "peer_path", "selected_peer_path")
    )
    attempts = _clean_list(
        headers.get("x-norllama-attempts")
        or _response_field(payload, "attempts", "attempted_upstreams")
        or _response_field(raw, "attempts", "attempted_upstreams")
    )
    gateway_request_id = _clean(headers.get("x-norllama-request-id"))
    if not peer_path and attempts:
        peer_path = [
            label
            for attempt in attempts
            if (label := _worker_label_for_endpoint(attempt))
        ]
    elif peer_path:
        peer_path = [
            label for item in peer_path if (label := _worker_label_for_value(item))
        ]
    worker = _worker_by_id(worker_id) if worker_id else {}
    if not worker and worker_endpoint:
        worker = _worker_by_endpoint(worker_endpoint)
    if (
        not worker
        and not worker_id
        and not worker_endpoint
        and not peer_path
        and not gateway_request_id
    ):
        return route
    attribution = dict(route.attribution or {})
    target_worker_id = _clean(
        attribution.get("target_worker_id")
        or (
            attribution.get("worker_id")
            if _clean(attribution.get("selection_source"))
            in {"policy_worker", "configured_worker_endpoint"}
            else ""
        )
    )
    if worker:
        response_worker_id = _clean(worker.get("id"))
        attribution.update(
            {
                "routing_scope": "direct_worker"
                if not attribution.get("frontdoor")
                else "frontdoor_worker",
                "selection_source": "gateway_response",
                "exact_worker": True,
                "worker_id": response_worker_id,
                "target_worker_id": target_worker_id,
                "gateway_selected_worker": response_worker_id,
                "observed_worker": response_worker_id,
                "observed_worker_source": "gateway_response",
                "worker_name": worker.get("name", ""),
                "worker_role": worker.get("role", ""),
                "worker_endpoint": worker.get("base_url", ""),
                "worker_memory_gb": worker.get("memory_gb"),
            }
        )
    elif worker_id:
        response_worker_id = _worker_label_for_value(worker_id)
        attribution.update(
            {
                "routing_scope": "frontdoor_worker"
                if attribution.get("frontdoor")
                else "direct_worker",
                "selection_source": "gateway_response",
                "exact_worker": True,
                "worker_id": response_worker_id,
                "target_worker_id": target_worker_id,
                "gateway_selected_worker": response_worker_id,
                "observed_worker": response_worker_id,
                "observed_worker_source": "gateway_response",
            }
        )
    if worker_endpoint:
        attribution["worker_endpoint"] = _public_endpoint(worker_endpoint)
    if peer_path:
        attribution["peer_path"] = peer_path
    if attempts:
        attribution["attempts"] = [_public_endpoint(attempt) for attempt in attempts]
    if gateway_request_id:
        attribution["gateway_request_id"] = gateway_request_id
    return replace(route, attribution=attribution)


def _default_endpoint(provider: str) -> str:
    if provider in NORLLAMA_PROVIDER_ALIASES:
        return _clean(getattr(settings, "llm_offline_base_url", ""))
    if provider in {"bedrock", "aws-bedrock"}:
        return _clean(getattr(settings, "llm_backup_base_url", ""))
    if provider.startswith("openai"):
        return _clean(getattr(settings, "llm_primary_base_url", ""))
    return ""


def _default_model(provider: str) -> str:
    if provider in NORLLAMA_PROVIDER_ALIASES:
        return _clean(getattr(settings, "llm_offline_model", ""))
    if provider in {"bedrock", "aws-bedrock"}:
        return _clean(getattr(settings, "llm_backup_model", ""))
    if provider.startswith("openai"):
        return _clean(getattr(settings, "llm_primary_model", "")) or _clean(
            getattr(settings, "openai_default_model", "")
        )
    return ""


def _cloud_mode(provider: str) -> str:
    if provider in {"openai", "openai-direct"}:
        return "primary"
    if provider in CLOUD_PROXY_PROVIDERS:
        return "backup_online"
    return "offline_local"


def _local_route(
    request: NorllamaTaskRequest,
    *,
    provider: str,
    reason: str,
    endpoint: str = "",
    model: str = "",
    model_selection: dict[str, Any] | None = None,
    provider_kind: str = "",
) -> NorllamaRoute:
    policy = request.route_policy
    endpoint = endpoint or _route_endpoint(policy, provider)
    public_provider = "norllama" if provider in NORLLAMA_PROVIDER_ALIASES else provider
    model_selection = model_selection or (
        {
            "schema": "norman.norllama.model-selection.v1",
            "selected": True,
            "model": model,
            "source": "caller_supplied",
            "reason": "model supplied by caller",
        }
        if model
        else _route_model_selection(policy, provider, task_kind=request.kind)
    )
    attribution = _base_attribution(
        provider=public_provider,
        endpoint=endpoint,
        policy=policy,
        cloud_proxy=False,
    )
    attribution["model_selection"] = model_selection
    return NorllamaRoute(
        lane=_route_policy_value(policy, "lane", "preferred_lane")
        or f"norllama_{_CAPABILITY_BY_KIND[request.kind]}",
        provider=public_provider,
        provider_kind=provider_kind or provider or "norllama",
        capability=_CAPABILITY_BY_KIND[request.kind],
        model=_clean(model_selection.get("model")),
        endpoint=endpoint,
        mode="offline_local",
        local=True,
        cloud_proxy=False,
        tool_lane=request.kind in TOOL_TASK_KINDS,
        requires_receipt=True,
        reason=reason,
        attribution=attribution,
    )


def _cloud_route(
    request: NorllamaTaskRequest,
    *,
    provider: str,
    reason: str,
) -> NorllamaRoute:
    policy = request.route_policy
    endpoint = _route_policy_value(policy, "endpoint", "base_url") or _default_endpoint(
        provider
    )
    model = _route_policy_value(policy, "model", "preferred_model") or _default_model(
        provider
    )
    attribution = _base_attribution(
        provider=provider,
        endpoint=endpoint,
        policy=policy,
        cloud_proxy=True,
    )
    attribution["model_selection"] = {
        "schema": "norman.norllama.model-selection.v1",
        "selected": bool(model),
        "model": model,
        "source": "cloud_provider",
        "reason": reason,
    }
    return NorllamaRoute(
        lane=_route_policy_value(policy, "lane", "preferred_lane")
        or f"norllama_cloud_{_CAPABILITY_BY_KIND[request.kind]}",
        provider=provider,
        provider_kind=provider,
        capability=_CAPABILITY_BY_KIND[request.kind],
        model=model,
        endpoint=endpoint,
        mode=_cloud_mode(provider),
        local=False,
        cloud_proxy=True,
        tool_lane=False,
        requires_receipt=True,
        reason=reason,
        attribution=attribution,
    )


def route_task(request: NorllamaTaskRequest) -> NorllamaRoute:
    """Select the Norman lane for a Norllama task.

    Norllama is the framework here, not just the local model. This router can
    select a local tool/model lane or proxy to a cloud executor while preserving
    the same task/receipt contract for TUIs and audit streams.
    """

    policy = request.route_policy
    preferred_provider = _normalize_provider(
        _route_policy_value(
            policy,
            "provider",
            "preferred_provider",
            "provider_surface",
            "runtime",
        )
    )
    offline_provider = _normalize_provider(
        _clean(getattr(settings, "llm_offline_provider", ""))
    )
    provider = preferred_provider or offline_provider or "norllama"
    uses_offline_slot = not preferred_provider or provider == offline_provider
    route_authorization = _route_policy_authorization(
        policy,
        execution_mode="route_task",
        provider=provider,
        model=_route_policy_value(policy, "model", "preferred_model"),
        lane=_route_policy_value(policy, "lane", "preferred_lane")
        or _task_kind_value(request.kind),
    )
    if not route_authorization.get("allowed"):
        blocked_selection = {
            "schema": "norman.norllama.model-selection.v1",
            "selected": False,
            "model": "",
            "source": "route_policy_blocked",
            "reason": _clean(route_authorization.get("reason"))
            or "route policy blocked route selection",
            "policy_authorization": route_authorization,
            "production_route_eligible": False,
        }
        return _local_route(
            request,
            provider="norllama",
            reason="route policy blocked production route selection",
            endpoint="",
            model="",
            model_selection=blocked_selection,
            provider_kind="norllama",
        )
    endpoint = _route_endpoint(
        request.route_policy, provider, offline_slot=uses_offline_slot
    )
    model_selection = _route_model_selection(
        request.route_policy,
        provider,
        offline_slot=uses_offline_slot,
        task_kind=request.kind,
    )
    model = _clean(model_selection.get("model"))
    openai_compatible_frontdoor = (
        provider in OPENAI_COMPATIBLE_PROVIDERS
        and _endpoint_is_local_frontdoor(endpoint)
    )

    if request.kind in TOOL_TASK_KINDS:
        if provider in CLOUD_PROXY_PROVIDERS and _flag(
            policy.get("allow_cloud_tool_proxy")
        ):
            return _cloud_route(
                request,
                provider=provider,
                reason="tool task explicitly allowed to use cloud proxy",
            )
        return _local_route(
            request,
            provider="norllama" if provider in CLOUD_PROXY_PROVIDERS else provider,
            reason="tool task routed to local Norllama capability lane",
            endpoint=endpoint if openai_compatible_frontdoor else "",
            model=model,
            model_selection=model_selection,
            provider_kind="norllama" if openai_compatible_frontdoor else "",
        )

    if openai_compatible_frontdoor:
        return _local_route(
            request,
            provider="norllama",
            reason="OpenAI-compatible endpoint is the local Norllama front door",
            endpoint=endpoint,
            model=model,
            model_selection=model_selection,
            provider_kind="norllama",
        )

    if provider in CLOUD_PROXY_PROVIDERS and _flag(policy.get("allow_cloud_proxy")):
        return _cloud_route(
            request,
            provider=provider,
            reason="task routed through Norllama cloud proxy",
        )

    return _local_route(
        request,
        provider="norllama" if provider in CLOUD_PROXY_PROVIDERS else provider,
        reason="task routed to local Norllama lane"
        if provider not in CLOUD_PROXY_PROVIDERS
        else "cloud proxy not explicitly allowed; using local Norllama lane",
        model=model,
        model_selection=model_selection,
    )


def _policy_mode(policy: dict[str, Any]) -> str:
    configured = _route_policy_value(policy, "policy_mode", "mode", "offline_mode")
    if configured:
        return configured
    return (
        "local_first" if _flag(policy.get("local_first"), False) else "primary_online"
    )


def _usage_bucket(route: NorllamaRoute) -> str:
    provider = _normalize_provider(route.provider or route.provider_kind)
    if route.cloud_proxy:
        if provider in {"bedrock", "aws-bedrock"}:
            return "bedrock_amazon"
        if provider.startswith("openai") or provider == "codex":
            return "openai_codex"
        return "other_cloud"
    if route.local:
        return "offline_local"
    if provider == "perplexity":
        return "perplexity_web"
    if provider in {"bedrock", "aws-bedrock"}:
        return "bedrock_amazon"
    if provider.startswith("openai") or provider == "codex":
        return "openai_codex"
    return "other_cloud"


def _output_shape(
    *,
    status: str,
    output: dict[str, Any],
    error: str,
) -> str:
    if error:
        return "error"
    clean_status = _clean(status).lower()
    if clean_status in {"failed", "error", "timeout"}:
        return "error" if clean_status != "timeout" else "timeout"
    text = _clean(
        output.get("text")
        or output.get("response")
        or output.get("response_preview")
        or output.get("summary")
    )
    if clean_status in {"planned", "accepted"} and output.get("adapter_required"):
        return "progress_only"
    if not text and not output:
        return "empty"
    if clean_status in {"planned", "accepted", "checkpointed"}:
        return "progress_only"
    return "complete" if text or output else "empty"


def _token_count(output: dict[str, Any], *keys: str) -> int:
    usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}
    for key in keys:
        value = output.get(key)
        if value in ("", None):
            value = usage.get(key)
        if value in ("", None):
            continue
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            continue
    return 0


def route_receipt_payload(
    request: NorllamaTaskRequest,
    route: NorllamaRoute,
    *,
    status: str = "planned",
    output: dict[str, Any] | None = None,
    error: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = output or {}
    metadata = metadata or {}
    attribution = route.attribution if isinstance(route.attribution, dict) else {}
    selection = (
        attribution.get("model_selection")
        if isinstance(attribution.get("model_selection"), dict)
        else {}
    )
    quality = (
        selection.get("benchmark_quality")
        if isinstance(selection.get("benchmark_quality"), dict)
        else {}
    )
    gateway_receipt = _gateway_receipt(output)
    guardrail = (
        selection.get("route_guardrail")
        if isinstance(selection.get("route_guardrail"), dict)
        else {}
    )
    reality = (
        guardrail.get("model_reality")
        if isinstance(guardrail.get("model_reality"), dict)
        else {}
    )
    worker_id = _clean(attribution.get("worker_id"))
    gateway_selected_worker = _clean(
        attribution.get("gateway_selected_worker")
        or output.get("gateway_selected_worker")
        or metadata.get("gateway_selected_worker")
    )
    observed_worker = _clean(
        attribution.get("observed_worker")
        or output.get("observed_worker")
        or metadata.get("observed_worker")
        or (
            gateway_selected_worker
            if _clean(attribution.get("selection_source")) == "gateway_response"
            else ""
        )
    )
    target_worker = _clean(
        output.get("target_worker")
        or metadata.get("target_worker")
        or request.metadata.get("target_worker")
        or selection.get("target_worker")
        or attribution.get("target_worker_id")
        or (
            worker_id
            if _clean(attribution.get("selection_source"))
            in {"policy_worker", "configured_worker_endpoint"}
            else ""
        )
    )
    selected_worker = (
        target_worker
        or observed_worker
        or worker_id
        or ("cloud" if route.cloud_proxy or not route.local else "")
    )
    frontdoor = _public_endpoint(getattr(settings, "llm_offline_base_url", ""))
    peer_path = _clean_list(attribution.get("peer_path"))
    if not peer_path and frontdoor:
        peer_path = [frontdoor]
        peer_worker = observed_worker or selected_worker
        if peer_worker and peer_worker != "cloud":
            peer_path.append(peer_worker)
    phase = _clean(
        metadata.get("phase")
        or metadata.get("goal_phase")
        or request.metadata.get("phase")
        or request.metadata.get("goal_phase")
    ) or _task_kind_value(request.kind)
    input_tokens = _token_count(output, "input_tokens", "prompt_tokens")
    output_tokens = _token_count(output, "output_tokens", "completion_tokens")
    total_tokens = _token_count(output, "total_tokens")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    usage_bucket = _usage_bucket(route)
    raw = output.get("raw") if isinstance(output.get("raw"), dict) else {}
    target_model = _clean(
        output.get("target_model")
        or metadata.get("target_model")
        or selection.get("model")
        or route.model
    )
    route_selected_model = _clean(
        output.get("route_selected_model")
        or metadata.get("route_selected_model")
        or request.metadata.get("route_selected_model")
        or route.model
    )
    requested_model = _clean(
        output.get("requested_model")
        or metadata.get("requested_model")
        or request.metadata.get("requested_model")
        or target_model
        or route_selected_model
    )
    effective_runtime_model = _clean(
        output.get("effective_runtime_model")
        or output.get("runtime_model")
        or output.get("model")
        or gateway_receipt.get("effective_runtime_model")
        or gateway_receipt.get("model")
        or raw.get("model")
        or target_model
    )
    attribution_source = _clean(
        attribution.get("observed_worker_source") or attribution.get("selection_source")
    )
    routing_scope = _clean(attribution.get("routing_scope"))
    specialist_cascade = (
        output.get("specialist_cascade")
        if isinstance(output.get("specialist_cascade"), dict)
        else metadata.get("specialist_cascade")
        if isinstance(metadata.get("specialist_cascade"), dict)
        else request.metadata.get("specialist_cascade")
        if isinstance(request.metadata.get("specialist_cascade"), dict)
        else {}
    )
    if specialist_cascade:
        specialist_cascade = dict(specialist_cascade)
    else:
        specialist_cascade = specialist_cascade_template(
            phase=phase,
            selected_provider=route.provider,
            selected_model=target_model or route.model,
            selected_worker=selected_worker,
            usage_bucket=usage_bucket,
        )
    verifier_result = _clean(
        metadata.get("verifier_result")
        or output.get("verifier_result")
        or gateway_receipt.get("verifier_result")
    )
    output_shape = _clean(gateway_receipt.get("output_shape")) or _output_shape(
        status=status,
        output=output,
        error=error,
    )
    headers = _headers(output)
    client_request_id = _clean(
        output.get("client_request_id")
        or metadata.get("client_request_id")
        or request.metadata.get("client_request_id")
        or request.task_id
    )
    gateway_request_id = _clean(
        output.get("gateway_request_id")
        or metadata.get("gateway_request_id")
        or gateway_receipt.get("gateway_request_id")
        or headers.get("x-norllama-request-id")
    )
    invocation_id = _clean(
        output.get("invocation_id")
        or metadata.get("invocation_id")
        or request.metadata.get("invocation_id")
        or headers.get("x-norllama-invocation-id")
    )
    attempts = _clean_list(attribution.get("attempts"))
    fallback_used = bool(selection.get("fallback_used"))
    fallback_reason = (
        _clean(selection.get("fallback_reason") or selection.get("reason"))
        if not selection.get("selected", True)
        else ""
    )
    if target_worker and observed_worker and target_worker != observed_worker:
        fallback_used = True
        fallback_reason = (
            fallback_reason
            or f"gateway selected {observed_worker} instead of target {target_worker}"
        )
    elif len(attempts) > 1:
        fallback_used = True
        fallback_reason = fallback_reason or "gateway reported multiple worker attempts"
    policy_authorization = (
        attribution.get("route_policy_authorization")
        if isinstance(attribution.get("route_policy_authorization"), dict)
        else _route_policy_authorization(
            request.route_policy,
            execution_mode=_clean(
                metadata.get("execution_mode") or request.metadata.get("execution_mode")
            )
            or "route_receipt",
            provider=route.provider,
            model=target_model or route.model,
            lane=phase,
        )
    )
    policy_validation = (
        policy_authorization.get("validation")
        if isinstance(policy_authorization.get("validation"), dict)
        else {}
    )
    policy_artifact = _route_policy_artifact(request.route_policy)
    policy_manual_degraded = bool(
        policy_authorization.get("manual_degraded")
        or policy_authorization.get("manual_degraded_authorized")
    )

    receipt_payload = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": status,
        "request_id": request.task_id,
        "client_request_id": client_request_id,
        "gateway_request_id": gateway_request_id,
        "invocation_id": invocation_id,
        "job_id": _clean(
            request.metadata.get("console_runtime_job_id")
            or request.metadata.get("runtime_job_id")
            or request.metadata.get("job_id")
            or metadata.get("console_runtime_job_id")
            or metadata.get("runtime_job_id")
            or metadata.get("job_id")
        ),
        "phase": phase,
        "task_kind": _task_kind_value(request.kind),
        "selected_provider": route.provider,
        "selected_model": route.model,
        "route_selected_model": route_selected_model,
        "requested_model": requested_model,
        "target_model": target_model,
        "effective_runtime_model": effective_runtime_model,
        "model_override_used": bool(
            output.get("model_override_used")
            or metadata.get("model_override_used")
            or request.metadata.get("model_override_used")
        ),
        "model_override_reason": _clean(
            output.get("model_override_reason")
            or metadata.get("model_override_reason")
            or request.metadata.get("model_override_reason")
        ),
        "selected_worker": selected_worker,
        "target_worker": target_worker,
        "gateway_selected_worker": gateway_selected_worker,
        "observed_worker": observed_worker,
        "observed_worker_source": attribution_source if observed_worker else "",
        "route_attribution_source": attribution_source,
        "routing_scope": routing_scope,
        "frontdoor": frontdoor,
        "peer_path": peer_path,
        "attempts": attempts,
        "route_reason": route.reason,
        "policy_mode": _policy_mode(request.route_policy),
        "policy_id": _clean(
            policy_authorization.get("policy_id") or policy_artifact.get("policy_id")
        ),
        "policy_hash": _clean(
            policy_authorization.get("policy_hash")
            or policy_artifact.get("policy_hash")
        ),
        "policy_integrity_valid": bool(
            policy_authorization.get("integrity_valid")
            or policy_validation.get("integrity_valid")
        ),
        "policy_lifecycle_state": _clean(
            policy_authorization.get("lifecycle_state")
            or policy_validation.get("state")
        ),
        "policy_default_route_allowed": bool(
            policy_authorization.get("default_route_allowed")
            or policy_validation.get("default_route_allowed")
        ),
        "policy_issued_at": _clean(
            policy_authorization.get("policy_issued_at")
            or policy_artifact.get("issued_at")
        ),
        "policy_expires_at": _clean(
            policy_authorization.get("policy_expires_at")
            or policy_artifact.get("expires_at")
        ),
        "policy_refresh_generation": int(
            policy_authorization.get("policy_refresh_generation")
            or policy_artifact.get("refresh_generation")
            or 0
        ),
        "manual_degraded_authorized": policy_manual_degraded,
        "manual_degraded_authorization": policy_authorization.get(
            "manual_degraded_authorization"
        )
        if policy_manual_degraded
        else {},
        "policy_authorization": policy_authorization,
        "cloud_proxy": bool(route.cloud_proxy),
        "benchmark_packet_id": _clean(
            selection.get("benchmark_packet_id")
            or quality.get("packet_id")
            or metadata.get("benchmark_packet_id")
        ),
        "benchmark_source": _clean(
            quality.get("source")
            or selection.get("source")
            or metadata.get("benchmark_source")
        ),
        "benchmark_fresh": bool(
            quality.get("fresh")
            or selection.get("benchmark_fresh")
            or reality.get("proof_status") == "ready"
        ),
        "benchmark_score": quality.get("score") or 0.0,
        "coverage_ratio": quality.get("coverage_ratio") or 0.0,
        "benchmark_gate": quality.get("benchmark_gate")
        if isinstance(quality.get("benchmark_gate"), dict)
        else selection.get("benchmark_gate")
        if isinstance(selection.get("benchmark_gate"), dict)
        else {},
        "transport_gate": quality.get("transport_gate")
        if isinstance(quality.get("transport_gate"), dict)
        else selection.get("transport_gate")
        if isinstance(selection.get("transport_gate"), dict)
        else {},
        "capability_gate": quality.get("capability_gate")
        if isinstance(quality.get("capability_gate"), dict)
        else selection.get("capability_gate")
        if isinstance(selection.get("capability_gate"), dict)
        else {},
        "capability_suite_id": _clean(
            quality.get("capability_suite_id")
            or selection.get("capability_suite_id")
            or metadata.get("capability_suite_id")
        ),
        "capability_packet_id": _clean(
            quality.get("capability_packet_id")
            or selection.get("capability_packet_id")
            or metadata.get("capability_packet_id")
        ),
        "capability_promotion_authoritative": bool(
            quality.get("capability_promotion_authoritative")
            or selection.get("capability_promotion_authoritative")
        ),
        "production_route_requires_capability_gate": bool(
            quality.get("production_route_requires_capability_gate")
            or selection.get("production_route_requires_capability_gate")
        ),
        "production_route_eligible": bool(
            (
                quality.get("production_route_eligible")
                if "production_route_eligible" in quality
                else selection.get("production_route_eligible")
                if "production_route_eligible" in selection
                else True
            )
            and policy_authorization.get("production_route_eligible")
        ),
        "capability_route_state": _clean(
            quality.get("capability_route_state")
            or selection.get("capability_route_state")
        ),
        "promotion_authoritative": bool(
            quality.get("promotion_authoritative")
            or selection.get("promotion_authoritative")
        ),
        "cold_start_ms": _token_count(output, "cold_start_ms"),
        "first_token_ms": _token_count(output, "first_token_ms"),
        "completion_ms": _token_count(output, "completion_ms", "latency_ms"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usage_bucket": usage_bucket,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason or None,
        "verifier_result": verifier_result or "skipped",
        "output_shape": output_shape,
        "completion_requested": bool(
            metadata.get("completion_requested")
            or request.metadata.get("completion_requested")
        ),
        "require_verifier_for_completion": bool(
            metadata.get("require_verifier_for_completion")
            or request.metadata.get("require_verifier_for_completion")
        ),
        "model_selection": selection,
        "model_reality": reality,
        "execution_mode": _clean(
            metadata.get("execution_mode") or request.metadata.get("execution_mode")
        )
        or "unknown",
    }
    receipt_payload["specialist_cascade"] = evaluate_specialist_cascade(
        specialist_cascade,
        route_receipt=receipt_payload,
        output=output,
        metadata=metadata,
    )
    from app.services.norllama.route_proof import audit_route_receipt

    receipt_payload["receipt_audit"] = audit_route_receipt(receipt_payload)
    return receipt_payload


def build_task_receipt(
    request: NorllamaTaskRequest,
    route: NorllamaRoute | None = None,
    *,
    status: str = "planned",
    output: dict[str, Any] | None = None,
    evidence_paths: list[str] | None = None,
    confidence: float | None = None,
    error: str = "",
    metadata: dict[str, Any] | None = None,
) -> NorllamaReceipt:
    resolved_route = route or route_task(request)
    receipt_metadata = dict(metadata or {})
    receipt_metadata.setdefault(
        "route_receipt",
        route_receipt_payload(
            request,
            resolved_route,
            status=status,
            output=output or {},
            error=error,
            metadata=receipt_metadata,
        ),
    )
    return NorllamaReceipt(
        task_id=request.task_id,
        task_kind=request.kind,
        route=resolved_route,
        status=status,
        output=output or {},
        evidence_paths=evidence_paths or [],
        confidence=confidence,
        error=error,
        metadata=receipt_metadata,
    )
