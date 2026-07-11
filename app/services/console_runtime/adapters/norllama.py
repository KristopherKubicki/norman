from __future__ import annotations

from app.core.config import settings
from app.services.console_runtime.types import (
    ModelCapabilities,
    ModelRequest,
    ModelResult,
    ModelUsage,
)
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.capability_catalog import catalog_payload
from app.services.norllama.routing import (
    build_task_receipt,
    route_task,
    with_response_attribution,
)
from app.services.norllama.types import NorllamaTaskKind, NorllamaTaskRequest
from app.services.norllama.types import NorllamaRoute


TASK_KIND_ALIASES = {
    "draft": "chat",
    "execute": "chat",
    "literal_response": "chat",
    "tool": "chat",
    "tools": "chat",
    "work": "chat",
}


def _positive_float(value: object) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _model_timeout_seconds(request: ModelRequest) -> float:
    route_policy = (
        request.metadata.get("route_policy")
        if isinstance(request.metadata.get("route_policy"), dict)
        else {}
    )
    explicit_timeout = 0.0
    for source in (route_policy, request.metadata):
        if not isinstance(source, dict):
            continue
        for key in (
            "model_timeout_seconds",
            "norllama_timeout_seconds",
            "provider_timeout_seconds",
        ):
            explicit_timeout = _positive_float(source.get(key))
            if explicit_timeout:
                break
        if explicit_timeout:
            break
    default_timeout = _positive_float(
        getattr(settings, "console_runtime_norllama_timeout_seconds", 0)
    ) or _positive_float(getattr(settings, "llm_provider_timeout_seconds", 0))
    timeout = explicit_timeout or default_timeout or 45.0
    budget_timeout = _positive_float(getattr(request.budget, "max_runtime_seconds", 0))
    if budget_timeout:
        timeout = min(timeout, budget_timeout)
    return max(1.0, timeout)


def _metadata_value(metadata: dict, *keys: str) -> str:
    for key in keys:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _job_id_from_invocation_id(invocation_id: str) -> str:
    parts = str(invocation_id or "").strip().split(":")
    if len(parts) >= 3 and parts[0] == "worker" and parts[1].strip():
        return parts[1].strip()
    return ""


def _correlation_headers(request: ModelRequest, *, task_id: str) -> dict[str, str]:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    headers = {"X-Request-Id": task_id}
    invocation_id = _metadata_value(metadata, "invocation_id")
    job_id = _metadata_value(
        metadata,
        "console_runtime_job_id",
        "runtime_job_id",
        "job_id",
    ) or _job_id_from_invocation_id(invocation_id)
    session = _metadata_value(
        metadata,
        "console_runtime_session",
        "session_name",
        "session",
    )
    phase = _metadata_value(metadata, "goal_phase", "phase", "goal_task_kind")
    lane = _metadata_value(metadata, "goal_task_kind", "task_kind")
    if job_id:
        headers["X-Norman-Job-Id"] = job_id
    if session:
        headers["X-Norman-Session"] = session
    if phase:
        headers["X-Norman-Phase"] = phase
    if lane:
        headers["X-Norman-Lane"] = lane
    if invocation_id:
        headers["X-Norllama-Invocation-Id"] = invocation_id
    return headers


def _lower_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip().lower(): str(header_value or "").strip()
        for key, header_value in value.items()
        if str(key or "").strip()
    }


def _task_kind_from_metadata(metadata: dict) -> NorllamaTaskKind:
    for key in (
        "norllama_task_kind",
        "goal_task_kind",
        "task_kind",
        "goal_phase",
        "phase",
    ):
        clean = str(metadata.get(key) or "").strip().lower()
        if not clean:
            continue
        clean = TASK_KIND_ALIASES.get(clean, clean)
        try:
            return NorllamaTaskKind(clean)
        except ValueError:
            continue
    return NorllamaTaskKind.CHAT


def _route_from_metadata(metadata: dict) -> NorllamaRoute | None:
    value = metadata.get("norllama_route")
    if not isinstance(value, dict):
        value = metadata.get("route")
    if not isinstance(value, dict):
        return None
    allowed = set(NorllamaRoute.__dataclass_fields__)
    payload = {key: value.get(key) for key in allowed if key in value}
    try:
        return NorllamaRoute(**payload)
    except TypeError:
        return None


class NorllamaModelAdapter:
    """Console runtime adapter for Norman's Norllama task framework."""

    name = "norllama"

    @property
    def capabilities(self) -> ModelCapabilities:
        model = str(getattr(settings, "llm_offline_model", "") or "").strip()
        live: dict = {}
        try:
            live = norllama_gateway.fetch_capabilities(
                base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
                api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
                timeout_seconds=2,
            )
        except Exception:
            live = {}
        supports = (
            live.get("supports") if isinstance(live.get("supports"), dict) else {}
        )
        live_models = live.get("models") if isinstance(live.get("models"), list) else []
        models = [str(item).strip() for item in live_models if str(item).strip()]
        if model and model not in models:
            models.insert(0, model)
        return ModelCapabilities(
            provider=self.name,
            models=models,
            supports_tools=bool(supports.get("tools") or not live),
            supports_streaming=bool(supports.get("streaming")),
            supports_files=bool(supports.get("files") or not live),
            local=True,
            metadata={
                "task_framework": "norllama",
                "cloud_proxy_supported": True,
                "tool_lanes": live.get("tool_lanes")
                if isinstance(live.get("tool_lanes"), list)
                else ["ocr", "stt", "embed", "rerank"],
                "task_kinds": live.get("task_kinds")
                if isinstance(live.get("task_kinds"), list)
                else [],
                "modalities": live.get("modalities")
                if isinstance(live.get("modalities"), list)
                else [],
                "capability_catalog": catalog_payload(),
                "capability_contracts": live.get("contracts")
                if isinstance(live.get("contracts"), list)
                else [],
                "frontdoor_endpoints": live.get("endpoints")
                if isinstance(live.get("endpoints"), list)
                else [],
                "capabilities_endpoint": bool(live),
            },
        )

    def invoke(self, request: ModelRequest) -> ModelResult:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        task_id = _metadata_value(metadata, "request_id", "invocation_id")
        task_kind = _task_kind_from_metadata(metadata)
        task = NorllamaTaskRequest(
            kind=task_kind,
            messages=request.messages,
            route_policy=request.metadata.get("route_policy")
            if isinstance(request.metadata.get("route_policy"), dict)
            else {"provider": "norllama"},
            metadata=request.metadata,
            task_id=task_id,
        )
        route = _route_from_metadata(metadata) or route_task(task)
        model = (
            request.model
            or _metadata_value(metadata, "requested_model")
            or route.model
            or str(settings.llm_offline_model)
        )
        payload = norllama_gateway.invoke_text_chat(
            messages=request.messages,
            model=model,
            base_url=route.endpoint or str(settings.llm_offline_base_url),
            api_key=str(settings.llm_offline_api_key or ""),
            max_tokens=request.budget.max_output_tokens,
            timeout_seconds=_model_timeout_seconds(request),
            correlation_headers=_correlation_headers(request, task_id=task.task_id),
        )
        route = with_response_attribution(route, payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        headers = _lower_headers(payload.get("headers"))
        text = str(payload["choices"][0]["message"]["content"])
        effective_model = str(payload.get("model") or model)
        receipt = build_task_receipt(
            task,
            route,
            status="completed",
            output={
                "text": text,
                "response_preview": text[:200],
                "route_selected_model": _metadata_value(
                    metadata, "route_selected_model"
                )
                or route.model,
                "requested_model": _metadata_value(metadata, "requested_model")
                or model,
                "target_model": model,
                "effective_runtime_model": effective_model,
                "model": effective_model,
                "model_override_used": bool(metadata.get("model_override_used")),
                "model_override_reason": _metadata_value(
                    metadata, "model_override_reason"
                ),
                "usage": usage,
                "gateway_request_id": str(headers.get("x-norllama-request-id") or ""),
                "invocation_id": _metadata_value(metadata, "invocation_id"),
                "raw": payload.get("raw")
                if isinstance(payload.get("raw"), dict)
                else {},
            },
        )
        return ModelResult(
            provider=self.name,
            model=effective_model,
            text=text,
            stop_reason="stop",
            usage=ModelUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
            metadata={
                "norllama_route": route.as_dict(),
                "norllama_receipt": receipt.as_dict(),
            },
            raw=payload.get("raw") if isinstance(payload.get("raw"), dict) else {},
        )
