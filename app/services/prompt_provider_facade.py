from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from app.core.config import settings
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.route_proof import (
    audit_route_receipt,
    receipt_completion_gate_passes,
)
from app.services.norllama.route_policy import ROUTE_POLICY_MODELS
from app.services.norllama.routing import build_task_receipt
from app.services.norllama.types import NorllamaRoute, NorllamaTaskRequest
from app.services.prompt_load_balancer import provider_adapter_decision

SUPPORTED_CHAT_FIELDS = {
    "frequency_penalty",
    "max_completion_tokens",
    "max_tokens",
    "messages",
    "metadata",
    "model",
    "norman",
    "presence_penalty",
    "stream",
    "temperature",
    "top_p",
    "user",
}
SUPPORTED_RESPONSES_FIELDS = {
    "input",
    "instructions",
    "max_output_tokens",
    "max_tokens",
    "messages",
    "metadata",
    "model",
    "norman",
    "prompt",
    "previous_response_id",
    "stream",
    "temperature",
    "text",
    "tool_choice",
    "tools",
    "top_p",
    "user",
}
BEHAVIOR_BEARING_UNSUPPORTED_FIELDS = {
    "background",
    "conversation",
    "modalities",
    "parallel_tool_calls",
    "previous_response_id",
    "reasoning",
    "response_format",
    "stream_options",
    "text",
    "tool_choice",
    "tools",
}
MAX_FACADE_TOKENS = 4096
MAX_RESPONSE_STATE = 200
MODEL_ALIASES = {
    "norman-code": ROUTE_POLICY_MODELS["coding_operator"],
    "norman-fast": ROUTE_POLICY_MODELS["router"],
    "norman-local": "",
    "norman-reasoning": ROUTE_POLICY_MODELS["router"],
}
RAW_LOCAL_MODEL_MARKERS = (
    "bge",
    "gemma",
    "llama",
    "mistral",
    "qwen",
    "rerank",
)
_RESPONSE_STATE_LOCK = threading.RLock()
_RESPONSE_STATE: dict[str, dict[str, Any]] = {}
_RESPONSE_STATE_ORDER: deque[str] = deque()


class FacadeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_type: str = "invalid_request_error",
        code: str = "invalid_request",
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.param = param


@dataclass(frozen=True)
class FacadeAuthorization:
    allowed: bool
    model: str
    reason: str
    route: dict[str, Any]
    route_authorization: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "model": self.model,
            "reason": self.reason,
            "route_authorization": self.route_authorization,
        }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    lowered = _lower(value)
    if not lowered:
        return default
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _messages(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) else []


def reset_facade_response_state() -> None:
    with _RESPONSE_STATE_LOCK:
        _RESPONSE_STATE.clear()
        _RESPONSE_STATE_ORDER.clear()


def _store_response_state(
    response_id: str,
    *,
    messages: list[dict[str, Any]],
    output_text: str,
    output_items: list[dict[str, Any]],
) -> None:
    if not response_id:
        return
    with _RESPONSE_STATE_LOCK:
        _RESPONSE_STATE[response_id] = {
            "messages": [dict(message) for message in messages],
            "output_text": output_text,
            "output_items": [dict(item) for item in output_items],
            "created_at": time.time(),
        }
        _RESPONSE_STATE_ORDER.append(response_id)
        while len(_RESPONSE_STATE_ORDER) > MAX_RESPONSE_STATE:
            stale = _RESPONSE_STATE_ORDER.popleft()
            _RESPONSE_STATE.pop(stale, None)


def _previous_response_messages(previous_response_id: str) -> list[dict[str, Any]]:
    previous_response_id = _clean(previous_response_id)
    if not previous_response_id:
        return []
    with _RESPONSE_STATE_LOCK:
        state = dict(_RESPONSE_STATE.get(previous_response_id) or {})
    if not state:
        raise FacadeError(
            "Unknown previous_response_id for Norman Responses facade",
            status_code=404,
            code="previous_response_not_found",
            param="previous_response_id",
        )
    messages = _messages(state.get("messages"))
    output_text = _clean(state.get("output_text"))
    if output_text:
        messages.append({"role": "assistant", "content": output_text})
    return messages


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, MAX_FACADE_TOKENS)


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


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return _clean(value)


def _header_value(headers: Mapping[str, Any], *names: str) -> str:
    normalized = {_lower(key): _clean(value) for key, value in headers.items()}
    for name in names:
        value = normalized.get(_lower(name))
        if value:
            return value
    return ""


def _planned_attribution(route_envelope: Mapping[str, Any]) -> dict[str, Any]:
    return _nested_dict(route_envelope, "norman_route", "route", "attribution")


def _worker_from_endpoint(value: str) -> str:
    clean = _clean(value).lower()
    if not clean:
        return ""
    if "192.168.2.151" in clean or "spark-151" in clean:
        return "spark-151"
    if "192.168.2.150" in clean or "spark-150" in clean:
        return "spark-150"
    if "192.168.2.133" in clean or "mac-mini-133" in clean or "2.133" in clean:
        return "mac-mini-133"
    return ""


def _gateway_attribution(
    *,
    result: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    headers = result.get("headers") if isinstance(result.get("headers"), dict) else {}
    planned = _planned_attribution(route_envelope)
    target_worker = _clean(
        planned.get("target_worker_id")
        or planned.get("worker_id")
        or planned.get("target_worker")
    )
    observed_worker = _header_value(
        headers,
        "x-norllama-observed-worker",
        "x-norllama-worker",
        "x-norllama-worker-id",
    ) or _clean(planned.get("observed_worker"))
    if not observed_worker:
        observed_worker = _worker_from_endpoint(
            _header_value(
                headers,
                "x-norllama-worker-endpoint",
                "x-norllama-upstream",
            )
        )
    gateway_selected_worker = (
        _header_value(
            headers,
            "x-norllama-gateway-selected-worker",
            "x-norllama-selected-worker",
            "x-norllama-worker",
            "x-norllama-worker-id",
        )
        or observed_worker
    )
    return {
        "target_worker": target_worker,
        "gateway_selected_worker": gateway_selected_worker,
        "observed_worker": observed_worker,
        "observed_worker_source": "gateway_headers" if observed_worker else "",
        "headers": dict(headers),
    }


def _choice_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return _clean(message.get("content"))


def _norman_options(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("norman")
    return dict(value) if isinstance(value, Mapping) else {}


def _tools(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tools")
    return [dict(item) for item in value] if isinstance(value, list) else []


def _tool_name(tool: Mapping[str, Any]) -> str:
    function = _mapping(tool.get("function"))
    return _clean(function.get("name") or tool.get("name"))


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {_tool_name(tool) for tool in tools if _tool_name(tool)}


def _tool_contract_message(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    tools = _tools(payload)
    if not tools:
        return []
    compact = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        function = _mapping(tool.get("function"))
        compact.append(
            {
                "name": name,
                "type": _clean(tool.get("type")) or "function",
                "description": _clean(
                    function.get("description") or tool.get("description")
                ),
                "parameters": function.get("parameters")
                or tool.get("parameters")
                or {},
            }
        )
    if not compact:
        return []
    return [
        {
            "role": "system",
            "content": (
                "Norman facade tool contract: if a tool is required, respond "
                "with JSON only in this shape: "
                '{"tool_call":{"name":"tool_name","arguments":{}}}. '
                "Otherwise answer normally. Available tools: " + _json_dumps(compact)
            ),
        }
    ]


def _structured_output_message(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = _mapping(payload.get("text"))
    fmt = _mapping(text.get("format"))
    fmt_type = _lower(fmt.get("type"))
    if not fmt or fmt_type in {"", "text"}:
        return []
    if fmt_type in {"json_object", "json_schema"}:
        return [
            {
                "role": "system",
                "content": (
                    "Return only output that satisfies this structured response "
                    f"format: {_json_dumps(fmt)}"
                ),
            }
        ]
    raise FacadeError(
        f"Unsupported Responses text.format type: {fmt_type}",
        status_code=501,
        error_type="unsupported_parameter",
        code="unsupported_text_format",
        param="text.format",
    )


def _prepare_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    provider_payload = dict(payload)
    norman_options = _norman_options(provider_payload)
    if "adapter_mode" not in norman_options:
        provider_payload["norman"] = {**norman_options, "adapter_mode": "intelligence"}
    return provider_payload


def _nested_dict(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, Mapping) else {}


def _find_route_authorization(route_envelope: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [
        _nested_dict(
            route_envelope,
            "norman_route",
            "route",
            "attribution",
            "route_policy_authorization",
        ),
        _nested_dict(
            route_envelope,
            "norman_route",
            "decision",
            "metadata",
            "route_policy_authorization",
        ),
        _nested_dict(
            route_envelope,
            "norman_route",
            "decision",
            "metadata",
            "route_policy",
            "server_route_authority",
        ),
    ]
    return next((candidate for candidate in candidates if candidate), {})


def _fallback_local_model(route_envelope: Mapping[str, Any]) -> str:
    recommendation = _nested_dict(route_envelope, "norman_route", "recommendation")
    task_kind = _lower(recommendation.get("task_kind"))
    reasoning_tier = _lower(recommendation.get("reasoning_tier"))
    if task_kind in {"code", "coder", "patch"}:
        return ROUTE_POLICY_MODELS["coding_operator"]
    if reasoning_tier == "high_reasoning":
        return ROUTE_POLICY_MODELS["router"]
    return ROUTE_POLICY_MODELS["router"]


def _requested_model(payload: Mapping[str, Any]) -> str:
    return _clean(payload.get("model"))


def _validate_requested_model_alias(payload: Mapping[str, Any]) -> str:
    requested = _requested_model(payload)
    lowered = requested.lower()
    if not requested:
        return ""
    if lowered in MODEL_ALIASES:
        return MODEL_ALIASES[lowered]
    if any(marker in lowered for marker in RAW_LOCAL_MODEL_MARKERS):
        raise FacadeError(
            "Raw local backend model IDs require a privileged Norman route lock",
            status_code=403,
            error_type="policy_blocked",
            code="raw_model_not_allowed",
            param="model",
        )
    return ""


def _validate_supported_fields(
    payload: Mapping[str, Any],
    *,
    supported_fields: set[str],
) -> None:
    for key in payload:
        if key in supported_fields:
            continue
        if key in BEHAVIOR_BEARING_UNSUPPORTED_FIELDS:
            raise FacadeError(
                f"Unsupported OpenAI-compatible facade parameter: {key}",
                status_code=501,
                error_type="unsupported_parameter",
                code="unsupported_parameter",
                param=key,
            )
        raise FacadeError(
            f"Unknown OpenAI-compatible facade parameter: {key}",
            status_code=400,
            error_type="invalid_request_error",
            code="unknown_parameter",
            param=key,
        )


def _text_part_text(part: Mapping[str, Any]) -> str:
    part_type = _clean(part.get("type"))
    if part_type in {"input_text", "text"}:
        return _clean(part.get("text"))
    if part_type in {"output_text"}:
        return _clean(part.get("text"))
    raise FacadeError(
        f"Unsupported Responses input content item type: {part_type or '<blank>'}",
        status_code=501,
        error_type="unsupported_parameter",
        code="unsupported_input_content",
        param="input",
    )


def response_input_to_messages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    instructions = _clean(payload.get("instructions"))
    if instructions:
        messages.append({"role": "system", "content": instructions})
    raw_input = payload.get("input", payload.get("prompt"))
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, Mapping):
                raise FacadeError(
                    "Responses input items must be objects",
                    status_code=400,
                    code="invalid_input_item",
                    param="input",
                )
            item_type = _clean(item.get("type"))
            if item_type == "function_call":
                raise FacadeError(
                    "Responses function_call input items are generated by the model and are not valid caller input",
                    status_code=501,
                    error_type="unsupported_parameter",
                    code="unsupported_tool_item",
                    param="input",
                )
            if item_type == "function_call_output":
                call_id = _clean(item.get("call_id"))
                output = item.get("output")
                messages.append(
                    {
                        "role": "tool",
                        "content": f"Tool output for {call_id}: {_clean(output)}",
                    }
                )
                continue
            role = _clean(item.get("role")) or "user"
            content = item.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "\n".join(
                    _text_part_text(part)
                    for part in content
                    if isinstance(part, Mapping)
                )
            else:
                raise FacadeError(
                    "Responses input content must be text",
                    status_code=501,
                    error_type="unsupported_parameter",
                    code="unsupported_input_content",
                    param="input",
                )
            messages.append({"role": role, "content": text})
    elif raw_input is None:
        raise FacadeError("Missing Responses input", status_code=400, param="input")
    else:
        raise FacadeError(
            "Responses input must be text or a list of text input items",
            status_code=400,
            code="invalid_input",
            param="input",
        )
    return messages


def _extract_tool_calls(
    text: str,
    *,
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = _tool_names(tools)
    if not text or not names:
        return []
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    raw_calls: list[Any] = []
    if isinstance(payload, Mapping):
        if isinstance(payload.get("tool_call"), Mapping):
            raw_calls = [payload["tool_call"]]
        elif isinstance(payload.get("tool_calls"), list):
            raw_calls = payload["tool_calls"]
    calls: list[dict[str, Any]] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        name = _clean(raw.get("name"))
        if name not in names:
            continue
        arguments = raw.get("arguments", {})
        call_id = _clean(raw.get("call_id")) or f"call_{uuid.uuid4().hex}"
        calls.append(
            {
                "id": f"fc_{uuid.uuid4().hex}",
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "arguments": arguments
                if isinstance(arguments, str)
                else _json_dumps(arguments),
            }
        )
    return calls


def _response_output_items(
    *,
    text: str,
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if tool_calls:
        return [dict(item) for item in tool_calls]
    return [
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
    ]


def _route_from_envelope(
    route_envelope: Mapping[str, Any],
    *,
    model: str,
    gateway_attribution: Mapping[str, Any],
) -> NorllamaRoute:
    route = _nested_dict(route_envelope, "norman_route", "route")
    recommendation = _nested_dict(route_envelope, "norman_route", "recommendation")
    attribution = _mapping(route.get("attribution"))
    model_selection = _mapping(attribution.get("model_selection"))
    model_selection.setdefault("production_route_eligible", False)
    model_selection.setdefault("source", "prompt_intermediary_facade")
    attribution["model_selection"] = model_selection
    attribution["gateway_selected_worker"] = _clean(
        gateway_attribution.get("gateway_selected_worker")
    )
    attribution["observed_worker"] = _clean(gateway_attribution.get("observed_worker"))
    attribution["observed_worker_source"] = "gateway_response"
    attribution["selection_source"] = "gateway_response"
    if _clean(gateway_attribution.get("target_worker")):
        attribution["target_worker"] = _clean(gateway_attribution.get("target_worker"))
        attribution["target_worker_id"] = _clean(
            gateway_attribution.get("target_worker")
        )
    return NorllamaRoute(
        lane=_clean(route.get("lane") or recommendation.get("selected_lane") or "chat"),
        provider=_clean(route.get("provider") or "norllama"),
        provider_kind=_clean(route.get("provider_kind") or "norllama"),
        capability=_clean(
            route.get("capability") or recommendation.get("task_kind") or "chat"
        ),
        model=model,
        endpoint=_clean(route.get("endpoint")),
        mode=_clean(route.get("mode")) or "offline_local",
        local=_flag(route.get("local"), default=True),
        cloud_proxy=_flag(route.get("cloud_proxy")),
        tool_lane=_flag(route.get("tool_lane")),
        requires_receipt=True,
        reason=_clean(route.get("reason")) or "OpenAI-compatible facade route",
        attribution=attribution,
    )


def _facade_route_receipt(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    authorization: FacadeAuthorization,
    result: Mapping[str, Any],
    usage: Mapping[str, Any],
    gateway_attribution: Mapping[str, Any],
    invocation_id: str,
    text: str,
) -> dict[str, Any]:
    messages = _messages(
        provider_payload.get("messages")
    ) or response_input_to_messages(provider_payload)
    task = NorllamaTaskRequest(
        kind="chat",
        input_text=text or "OpenAI-compatible facade call",
        messages=messages,
        route_policy=_nested_dict(
            route_envelope, "norman_route", "decision", "metadata", "route_policy"
        ),
        metadata={
            "phase": "chat",
            "execution_mode": "prompt_intermediary_openai_facade",
            "job_id": invocation_id,
            "client_request_id": invocation_id,
            "invocation_id": invocation_id,
            "route_selected_model": authorization.model,
            "requested_model": authorization.model,
        },
        task_id=invocation_id,
    )
    route = _route_from_envelope(
        route_envelope,
        model=authorization.model,
        gateway_attribution=gateway_attribution,
    )
    receipt = build_task_receipt(
        task,
        route,
        status="completed",
        output={
            "summary": text,
            "text": text,
            "model": _clean(result.get("model")) or authorization.model,
            "target_model": authorization.model,
            "route_selected_model": authorization.model,
            "requested_model": authorization.model,
            "effective_runtime_model": _clean(result.get("model"))
            or authorization.model,
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "usage": dict(usage),
            "headers": dict(result.get("headers") or {}),
            "client_request_id": invocation_id,
            "gateway_request_id": _header_value(
                _mapping(result.get("headers")),
                "x-norllama-request-id",
                "x-request-id",
            ),
            "invocation_id": invocation_id,
            "gateway_selected_worker": _clean(
                gateway_attribution.get("gateway_selected_worker")
            ),
            "observed_worker": _clean(gateway_attribution.get("observed_worker")),
            "verifier_result": "pass",
        },
        metadata={
            "phase": "chat",
            "execution_mode": "prompt_intermediary_openai_facade",
            "completion_requested": True,
            "verifier_result": "pass",
            "client_request_id": invocation_id,
            "invocation_id": invocation_id,
            "gateway_selected_worker": _clean(
                gateway_attribution.get("gateway_selected_worker")
            ),
            "observed_worker": _clean(gateway_attribution.get("observed_worker")),
            "target_worker": _clean(gateway_attribution.get("target_worker")),
        },
    ).as_dict()
    route_receipt = _mapping(receipt.get("route_receipt"))
    route_receipt["production_route_eligible"] = False
    route_receipt["request_production_route_eligible"] = False
    route_receipt["completion_requested"] = True
    route_receipt["receipt_audit"] = audit_route_receipt(route_receipt)
    route_receipt["completion_gate"] = {
        "gate_passed": receipt_completion_gate_passes(
            route_receipt,
            audit=route_receipt["receipt_audit"],
            require_verifier=True,
        ),
        "require_verifier": True,
    }
    receipt["route_receipt"] = route_receipt
    return receipt


def authorize_facade_execution(
    route_envelope: Mapping[str, Any],
    *,
    provider_payload: Mapping[str, Any],
) -> FacadeAuthorization:
    selected_runtime = _lower(route_envelope.get("selected_runtime"))
    selected_provider = _lower(route_envelope.get("selected_provider"))
    norman_route = _nested_dict(route_envelope, "norman_route")
    recommendation = _nested_dict(norman_route, "recommendation")
    route = _nested_dict(norman_route, "route")
    decision = _nested_dict(norman_route, "decision")
    route_authorization = _find_route_authorization(route_envelope)
    model_alias = _validate_requested_model_alias(provider_payload)
    selected_model = _clean(route_envelope.get("selected_model")) or model_alias
    model = selected_model or _fallback_local_model(route_envelope)

    failures: list[str] = []
    if selected_runtime != "localllm":
        failures.append("selected_runtime_not_localllm")
    if selected_provider != "norllama":
        failures.append("selected_provider_not_norllama")
    if not _flag(route.get("local")):
        failures.append("route_not_local")
    if _flag(route.get("cloud_proxy")):
        failures.append("cloud_proxy_route")
    if not _flag(decision.get("allowed"), default=True):
        failures.append("route_decision_blocked")
    if not _flag(recommendation.get("execution_allowed"), default=True):
        failures.append("execution_not_allowed")
    if _flag(recommendation.get("requires_approval")):
        failures.append("approval_required")
    lifecycle = _lower(route_authorization.get("lifecycle_state"))
    if route_authorization:
        if not _flag(route_authorization.get("allowed"), default=True):
            failures.append("policy_authorization_blocked")
        if not _flag(route_authorization.get("integrity_valid")):
            failures.append("policy_integrity_invalid")
        if lifecycle not in {"valid", "expiring_soon"}:
            failures.append("policy_lifecycle_not_valid")
        if not _flag(route_authorization.get("default_route_allowed")):
            failures.append("policy_default_route_blocked")
    if not model:
        failures.append("no_local_model")

    if failures:
        raise FacadeError(
            "Norman policy blocked OpenAI-compatible facade execution: "
            + ", ".join(failures),
            status_code=403,
            error_type="policy_blocked",
            code="facade_policy_blocked",
        )

    return FacadeAuthorization(
        allowed=True,
        model=model,
        reason="local_route_authorized",
        route=dict(route_envelope),
        route_authorization=route_authorization,
    )


def _execute_authorized_chat(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    request_id: str,
) -> dict[str, Any]:
    authorization = authorize_facade_execution(
        route_envelope,
        provider_payload=provider_payload,
    )
    max_tokens = _positive_int(
        provider_payload.get("max_completion_tokens")
        or provider_payload.get("max_output_tokens")
        or provider_payload.get("max_tokens"),
        1024,
    )
    invocation_id = request_id or f"norman-openai-facade-{uuid.uuid4().hex}"
    result = norllama_gateway.invoke_text_chat(
        messages=messages,
        model=authorization.model,
        base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
        api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
        max_tokens=max_tokens,
        timeout_seconds=float(getattr(settings, "llm_provider_timeout_seconds", 45)),
        correlation_headers={
            "X-Request-Id": invocation_id,
            "X-Norman-Execution-Mode": "prompt_intermediary_openai_facade",
            "X-Norman-Phase": "chat",
            "X-Norman-Route-Authority": "prompt_intermediary",
            "X-Norman-Request-Production-Eligible": "false",
        },
    )
    text = _choice_text(result)
    if not text:
        raise FacadeError(
            "Local model returned empty content",
            status_code=502,
            error_type="server_error",
            code="empty_local_response",
        )
    usage = _usage(result)
    gateway_attribution = _gateway_attribution(
        result=result,
        route_envelope=route_envelope,
    )
    facade_receipt = _facade_route_receipt(
        provider_payload={**provider_payload, "messages": messages},
        route_envelope=route_envelope,
        authorization=authorization,
        result=result,
        usage=usage,
        gateway_attribution=gateway_attribution,
        invocation_id=invocation_id,
        text=text,
    )
    response_id = f"chatcmpl-norman-{uuid.uuid4().hex}"
    created = int(time.time())
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": _clean(result.get("model")) or authorization.model,
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
            "route": dict(route_envelope),
            "authorization": authorization.as_dict(),
            "local_execution": True,
            "cloud_forwarding": False,
            "streaming_mode": "buffered_sse"
            if provider_payload.get("stream")
            else "none",
            "norllama": gateway_attribution,
            "gateway_headers": gateway_attribution["headers"],
            "facade_receipt": facade_receipt,
            "route_receipt": facade_receipt.get("route_receipt", {}),
        },
    }


def execute_openai_chat_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
) -> dict[str, Any]:
    """Execute the OpenAI Chat Completions local text subset."""

    _validate_supported_fields(payload, supported_fields=SUPPORTED_CHAT_FIELDS)
    provider_payload = _prepare_payload(payload)
    messages = _messages(provider_payload.get("messages"))
    if not messages:
        raise FacadeError("Missing chat messages", status_code=400, param="messages")
    route_envelope = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload=provider_payload,
    )
    return _execute_authorized_chat(
        provider_payload=provider_payload,
        route_envelope=route_envelope,
        messages=messages,
        request_id=request_id,
    )


def execute_openai_responses_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
) -> dict[str, Any]:
    """Execute the OpenAI Responses local text subset with one route decision."""

    _validate_supported_fields(payload, supported_fields=SUPPORTED_RESPONSES_FIELDS)
    provider_payload = _prepare_payload(payload)
    previous_messages = _previous_response_messages(
        _clean(provider_payload.get("previous_response_id"))
    )
    messages = [
        *previous_messages,
        *_tool_contract_message(provider_payload),
        *_structured_output_message(provider_payload),
        *response_input_to_messages(provider_payload),
    ]
    route_payload = {**provider_payload, "input": messages}
    route_envelope = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload=route_payload,
    )
    chat_response = _execute_authorized_chat(
        provider_payload=route_payload,
        route_envelope=route_envelope,
        messages=messages,
        request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
    )
    text = _clean(chat_response["choices"][0]["message"]["content"])
    tools = _tools(provider_payload)
    tool_calls = _extract_tool_calls(text, tools=tools)
    output_items = _response_output_items(text=text, tool_calls=tool_calls)
    output_text = "" if tool_calls else text
    response_id = f"resp-norman-{uuid.uuid4().hex}"
    created = int(time.time())
    response = {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": chat_response["model"],
        "output": output_items,
        "output_text": output_text,
        "usage": {
            "input_tokens": chat_response["usage"]["prompt_tokens"],
            "output_tokens": chat_response["usage"]["completion_tokens"],
            "total_tokens": chat_response["usage"]["total_tokens"],
        },
        "norman": {
            **chat_response["norman"],
            "responses_compatibility": {
                "schema": "norman.responses-compatibility.v1",
                "previous_response_id": _clean(
                    provider_payload.get("previous_response_id")
                ),
                "history_replayed": bool(previous_messages),
                "tools_declared": len(tools),
                "tool_calls_returned": len(tool_calls),
                "tool_call_mode": "explicit_json_envelope" if tools else "none",
                "structured_output_requested": bool(
                    _mapping(provider_payload.get("text")).get("format")
                ),
            },
        },
    }
    _store_response_state(
        response_id,
        messages=messages,
        output_text=output_text or text,
        output_items=output_items,
    )
    return response


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
