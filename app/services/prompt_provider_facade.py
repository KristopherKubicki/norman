from __future__ import annotations

import time
import uuid
from typing import Any, Mapping

from app.core.config import settings
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.route_policy import ROUTE_POLICY_MODELS
from app.services.prompt_load_balancer import provider_adapter_decision


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _messages(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) else []


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _usage(payload: Mapping[str, Any]) -> dict[str, int]:
    raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    completion_tokens = int(
        raw.get("completion_tokens") or raw.get("output_tokens") or 0
    )
    total_tokens = int(raw.get("total_tokens") or prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _choice_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return _clean(message.get("content"))


def _nested_dict(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _fallback_local_model(route_envelope: Mapping[str, Any]) -> str:
    norman_route = _nested_dict(route_envelope, "norman_route")
    recommendation = _nested_dict(norman_route, "recommendation")
    task_kind = _clean(recommendation.get("task_kind")).lower()
    reasoning_tier = _clean(recommendation.get("reasoning_tier")).lower()
    if task_kind in {"code", "coder", "patch"}:
        return ROUTE_POLICY_MODELS["coding_operator"]
    if reasoning_tier == "high_reasoning":
        return ROUTE_POLICY_MODELS["router"]
    return ROUTE_POLICY_MODELS["router"]


def _selected_local_model(route_envelope: Mapping[str, Any]) -> str:
    selected_runtime = _clean(route_envelope.get("selected_runtime")).lower()
    selected_provider = _clean(route_envelope.get("selected_provider")).lower()
    selected_model = _clean(route_envelope.get("selected_model"))
    if selected_runtime != "localllm" and selected_provider != "norllama":
        raise RuntimeError(
            "Norman selected a non-local provider; cloud forwarding is not enabled "
            "for the OpenAI-compatible facade"
        )
    return selected_model or _fallback_local_model(route_envelope)


def execute_openai_chat_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
) -> dict[str, Any]:
    """Execute an OpenAI chat-completions shaped request through Norman/Norllama."""

    provider_payload = dict(payload)
    norman_options = (
        provider_payload.get("norman")
        if isinstance(provider_payload.get("norman"), dict)
        else {}
    )
    if "adapter_mode" not in norman_options:
        provider_payload["norman"] = {**norman_options, "adapter_mode": "intelligence"}
    route_envelope = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload=provider_payload,
    )
    model = _selected_local_model(route_envelope)
    messages = _messages(provider_payload.get("messages"))
    max_tokens = _positive_int(
        provider_payload.get("max_completion_tokens")
        or provider_payload.get("max_tokens"),
        1024,
    )
    invocation_id = request_id or f"norman-openai-chat-{uuid.uuid4().hex}"
    result = norllama_gateway.invoke_text_chat(
        messages=messages,
        model=model,
        base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
        api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
        max_tokens=max_tokens,
        timeout_seconds=float(getattr(settings, "llm_provider_timeout_seconds", 45)),
        correlation_headers={
            "X-Request-Id": invocation_id,
            "X-Norman-Execution-Mode": "prompt_intermediary_openai_facade",
            "X-Norman-Phase": "chat",
            "X-Norman-Route-Authority": "prompt_intermediary",
        },
    )
    text = _choice_text(result)
    if not text:
        raise RuntimeError("local model returned empty content")
    usage = _usage(result)
    response_id = f"chatcmpl-norman-{uuid.uuid4().hex}"
    created = int(time.time())
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": _clean(result.get("model")) or model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "norman": {
            "schema": "norman.openai-compatible-facade.v1",
            "request_id": invocation_id,
            "route": route_envelope,
            "local_execution": True,
            "cloud_forwarding": False,
            "gateway_headers": result.get("headers")
            if isinstance(result.get("headers"), dict)
            else {},
        },
    }


def execute_openai_responses_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
) -> dict[str, Any]:
    """Execute an OpenAI responses shaped request through Norman/Norllama."""

    provider_payload = dict(payload)
    norman_options = (
        provider_payload.get("norman")
        if isinstance(provider_payload.get("norman"), dict)
        else {}
    )
    if "adapter_mode" not in norman_options:
        provider_payload["norman"] = {**norman_options, "adapter_mode": "intelligence"}
    route_envelope = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload=provider_payload,
    )
    prompt = _clean(route_envelope.get("normalized_prompt"))
    chat_payload = {
        "model": provider_payload.get("model"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": provider_payload.get("max_output_tokens")
        or provider_payload.get("max_tokens"),
        "norman": provider_payload.get("norman"),
    }
    chat_response = execute_openai_chat_facade(
        chat_payload,
        request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
    )
    text = _clean(chat_response["choices"][0]["message"]["content"])
    response_id = f"resp-norman-{uuid.uuid4().hex}"
    created = int(time.time())
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": chat_response["model"],
        "output": [
            {
                "id": f"msg-norman-{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": text,
        "usage": {
            "input_tokens": chat_response["usage"]["prompt_tokens"],
            "output_tokens": chat_response["usage"]["completion_tokens"],
            "total_tokens": chat_response["usage"]["total_tokens"],
        },
        "norman": {
            **chat_response["norman"],
            "route": route_envelope,
        },
    }


def chat_completion_stream_chunks(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = _clean(
        response.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(response.get("choices"), list)
        else ""
    )
    model = _clean(response.get("model"))
    response_id = _clean(response.get("id"))
    created = int(response.get("created") or time.time())
    return [
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"content": text}, "finish_reason": None}
            ],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
