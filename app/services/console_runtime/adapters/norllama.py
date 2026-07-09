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
        task = NorllamaTaskRequest(
            kind=NorllamaTaskKind.CHAT,
            messages=request.messages,
            route_policy=request.metadata.get("route_policy")
            if isinstance(request.metadata.get("route_policy"), dict)
            else {"provider": "norllama"},
            metadata=request.metadata,
        )
        route = route_task(task)
        model = request.model or route.model or str(settings.llm_offline_model)
        payload = norllama_gateway.invoke_text_chat(
            messages=request.messages,
            model=model,
            base_url=route.endpoint or str(settings.llm_offline_base_url),
            api_key=str(settings.llm_offline_api_key or ""),
            max_tokens=request.budget.max_output_tokens,
            timeout_seconds=_model_timeout_seconds(request),
        )
        route = with_response_attribution(route, payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        text = str(payload["choices"][0]["message"]["content"])
        effective_model = str(payload.get("model") or model)
        receipt = build_task_receipt(
            task,
            route,
            status="completed",
            output={
                "text": text,
                "response_preview": text[:200],
                "target_model": model,
                "effective_runtime_model": effective_model,
                "model": effective_model,
                "usage": usage,
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
