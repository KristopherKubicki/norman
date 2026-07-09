from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.routing import (
    TOOL_TASK_KINDS,
    build_task_receipt,
    route_task,
    with_response_attribution,
)
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskKind,
    NorllamaTaskRequest,
)

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore


ToolHandler = Callable[[NorllamaTaskRequest, NorllamaRoute], dict[str, Any]]
CloudHandler = Callable[[NorllamaTaskRequest, NorllamaRoute], dict[str, Any]]
LocalChatInvoker = Callable[..., dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _request_messages(request: NorllamaTaskRequest) -> list[dict[str, Any]]:
    if request.messages:
        return request.messages
    parts: list[str] = []
    if request.input_text:
        parts.append(request.input_text)
    if request.query:
        parts.append(f"Query: {request.query}")
    if request.candidates:
        parts.append(f"Candidates: {request.candidates}")
    if request.artifacts:
        parts.append(f"Artifacts: {request.artifacts}")
    return [{"role": "user", "content": "\n\n".join(parts)}]


def _candidate_text(candidate: dict[str, Any]) -> str:
    for key in ("text", "content", "document", "body"):
        value = _clean(candidate.get(key))
        if value:
            return value
    return _clean(candidate)


def _default_rerank_tool(
    request: NorllamaTaskRequest, route: NorllamaRoute
) -> dict[str, Any]:
    query = _clean(request.query or request.input_text)
    documents: list[Any] = request.candidates or [
        {"text": text}
        for text in (_clean(artifact.get("text")) for artifact in request.artifacts)
        if text
    ]
    if not query:
        raise RuntimeError("Norllama rerank tool requires a query")
    if not documents:
        raise RuntimeError("Norllama rerank tool requires candidate documents")
    payload = norllama_gateway.rerank_documents(
        query=query,
        documents=documents,
        model=route.model,
        base_url=route.endpoint
        or _clean(getattr(settings, "llm_offline_base_url", "")),
        api_key=_clean(getattr(settings, "llm_offline_api_key", "")),
        top_n=int(request.route_policy.get("top_n") or len(documents)),
        timeout_seconds=request.route_policy.get("timeout_seconds"),
    )
    ranked_ids: list[str] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        index = result.get("index")
        try:
            candidate = request.candidates[int(index)] if request.candidates else {}
        except Exception:
            candidate = {}
        candidate_id = _clean(
            candidate.get("id") if isinstance(candidate, dict) else ""
        )
        if candidate_id:
            ranked_ids.append(candidate_id)
    return {**payload, "ranked_ids": ranked_ids}


def _default_safety_tool(
    request: NorllamaTaskRequest, route: NorllamaRoute
) -> dict[str, Any]:
    text = norllama_gateway.messages_to_prompt(_request_messages(request))
    if request.candidates:
        candidate_text = "\n\n".join(
            text
            for text in (_candidate_text(candidate) for candidate in request.candidates)
            if text
        )
        if candidate_text:
            text = (
                f"{text}\n\nCANDIDATES:\n{candidate_text}" if text else candidate_text
            )
    payload = norllama_gateway.classify_safety(
        text=text,
        model=route.model,
        base_url=route.endpoint
        or _clean(getattr(settings, "llm_offline_base_url", "")),
        api_key=_clean(getattr(settings, "llm_offline_api_key", "")),
        timeout_seconds=request.route_policy.get("timeout_seconds"),
    )
    return payload


def _default_tool_handlers() -> dict[str, ToolHandler]:
    return {
        "prompt_injection": _default_safety_tool,
        "rerank": _default_rerank_tool,
        "safety": _default_safety_tool,
    }


def _bedrock_converse(
    request: NorllamaTaskRequest, route: NorllamaRoute
) -> dict[str, Any]:
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; Bedrock proxy is unavailable")
    model = _clean(route.model)
    if not model:
        raise RuntimeError("Bedrock proxy route is missing a model")
    region = (
        _clean(request.route_policy.get("region"))
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )
    kwargs = {"region_name": region} if region else {}
    client = boto3.client("bedrock-runtime", **kwargs)
    messages = [
        {
            "role": "user" if message.get("role") != "assistant" else "assistant",
            "content": [{"text": _clean(message.get("content"))}],
        }
        for message in _request_messages(request)
        if _clean(message.get("content"))
    ]
    response = client.converse(
        modelId=model,
        messages=messages,
        inferenceConfig={
            "maxTokens": int(request.route_policy.get("max_tokens") or 1024),
            "temperature": float(request.route_policy.get("temperature") or 0),
        },
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = "\n".join(
        _clean(part.get("text"))
        for part in content
        if isinstance(part, dict) and _clean(part.get("text"))
    )
    return {
        "provider": "bedrock",
        "model": model,
        "text": text,
        "raw": response,
    }


class NorllamaProxy:
    """Invoke Norllama tasks across local, cloud, and specialized tool lanes."""

    def __init__(
        self,
        *,
        tool_handlers: dict[str, ToolHandler] | None = None,
        cloud_handlers: dict[str, CloudHandler] | None = None,
        local_chat: LocalChatInvoker | None = None,
    ) -> None:
        self._tool_handlers = _default_tool_handlers()
        self._tool_handlers.update(dict(tool_handlers or {}))
        self._cloud_handlers = dict(cloud_handlers or {})
        self._local_chat = local_chat or norllama_gateway.invoke_text_chat

    def invoke(self, request: NorllamaTaskRequest) -> NorllamaReceipt:
        route = route_task(request)
        started = time.perf_counter()
        try:
            if request.kind in TOOL_TASK_KINDS:
                return self._invoke_tool(request, route, started)
            if route.cloud_proxy:
                return self._invoke_cloud(request, route, started)
            return self._invoke_local_chat(request, route, started)
        except Exception as exc:
            return build_task_receipt(
                request,
                route,
                status="failed",
                error=str(exc),
                metadata={"latency_ms": self._latency_ms(started)},
            )

    def _invoke_tool(
        self,
        request: NorllamaTaskRequest,
        route: NorllamaRoute,
        started: float,
    ) -> NorllamaReceipt:
        handler = self._tool_handlers.get(route.capability)
        if handler is None:
            return build_task_receipt(
                request,
                route,
                status="planned",
                output={
                    "adapter_required": True,
                    "capability": route.capability,
                    "supported_tool_handlers": sorted(self._tool_handlers),
                },
                metadata={"latency_ms": self._latency_ms(started)},
            )
        output = handler(request, route)
        route = with_response_attribution(route, output)
        return build_task_receipt(
            request,
            route,
            status="completed",
            output=output,
            metadata={"latency_ms": self._latency_ms(started)},
        )

    def _invoke_cloud(
        self,
        request: NorllamaTaskRequest,
        route: NorllamaRoute,
        started: float,
    ) -> NorllamaReceipt:
        handler = (
            self._cloud_handlers.get(route.provider)
            or self._cloud_handlers.get(route.provider_kind)
            or self._default_cloud_handler(route)
        )
        return build_task_receipt(
            request,
            route,
            status="completed",
            output=handler(request, route),
            metadata={"latency_ms": self._latency_ms(started)},
        )

    def _invoke_local_chat(
        self,
        request: NorllamaTaskRequest,
        route: NorllamaRoute,
        started: float,
    ) -> NorllamaReceipt:
        model = route.model or _clean(getattr(settings, "llm_offline_model", ""))
        payload = self._local_chat(
            messages=_request_messages(request),
            model=model,
            base_url=route.endpoint
            or _clean(getattr(settings, "llm_offline_base_url", "")),
            api_key=_clean(getattr(settings, "llm_offline_api_key", "")),
            max_tokens=int(request.route_policy.get("max_tokens") or 1024),
        )
        route = with_response_attribution(route, payload)
        choices = (
            payload.get("choices") if isinstance(payload.get("choices"), list) else []
        )
        message = choices[0].get("message") if choices else {}
        return build_task_receipt(
            request,
            route,
            status="completed",
            output={
                "model": payload.get("model") or model,
                "text": _clean(message.get("content")),
                "usage": payload.get("usage") or {},
            },
            metadata={"latency_ms": self._latency_ms(started)},
        )

    def _default_cloud_handler(self, route: NorllamaRoute) -> CloudHandler:
        if route.provider in {"bedrock", "aws-bedrock"}:
            return _bedrock_converse
        raise RuntimeError(f"No Norllama cloud handler registered for {route.provider}")

    @staticmethod
    def _latency_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def invoke_task(request: NorllamaTaskRequest) -> NorllamaReceipt:
    return NorllamaProxy().invoke(request)
