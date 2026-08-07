from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from app.core.config import settings
from app.services.console_runtime.adapters.bedrock import BedrockModelAdapter
from app.services.console_runtime.types import ModelBudget, ModelRequest, ModelResult
from app.services.norllama import capacity as norllama_capacity
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.route_policy import (
    CLOUD_FALLBACK_BEDROCK_MODEL,
    cloud_fallback_allowed_for_alias,
    explicit_cloud_selection_for_model,
)
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
    "client_metadata",
    "input",
    "include",
    "instructions",
    "max_output_tokens",
    "max_tokens",
    "messages",
    "metadata",
    "model",
    "norman",
    "parallel_tool_calls",
    "prompt",
    "prompt_cache_key",
    "previous_response_id",
    "reasoning",
    "store",
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
    "previous_response_id",
    "response_format",
    "stream_options",
    "text",
    "tool_choice",
    "tools",
}
SUPPORTED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
SUPPORTED_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed", "none"})
SUPPORTED_REASONING_CONTEXTS = frozenset({"auto", "current_turn", "all_turns"})
SUPPORTED_RESPONSES_INCLUDE_VALUES = frozenset({"reasoning.encrypted_content"})
MAX_FACADE_TOKENS = 4096
MAX_RESPONSE_STATE = 200
CLOUD_FALLBACK_SCHEMA = "norman.cloud-fallback.v1"
CLOUD_FALLBACK_MARKER_SCHEMA = "norman.facade-cloud-fallback.v1"
CLOUD_FALLBACK_PROVIDER = "aws-bedrock"
CLOUD_FALLBACK_MODEL = CLOUD_FALLBACK_BEDROCK_MODEL
CLOUD_FALLBACK_LANE = "coder"
EXPLICIT_CLOUD_SELECTION_SCHEMA = "norman.explicit-cloud-selection.v1"
EXPLICIT_CLOUD_SELECTION_MARKER_SCHEMA = "norman.facade-explicit-cloud-selection.v1"
CODEX_APPS_TOOL_PREFIX = "mcp__codex_apps__"
IMPLICIT_TOOL_SEARCH_NAME = "tool_search"
MCP_RESOURCE_DISCOVERY_TOOL_NAMES = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
    }
)
logger = logging.getLogger(__name__)
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
        norman: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.param = param
        self.norman = dict(norman or {})
        self.headers = {
            str(key): str(value)
            for key, value in dict(headers or {}).items()
            if _clean(key) and _clean(value)
        }


@dataclass(frozen=True)
class FacadeAuthorization:
    allowed: bool
    model: str
    reason: str
    route: dict[str, Any]
    route_authorization: dict[str, Any]
    execution_advisory: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "model": self.model,
            "reason": self.reason,
            "route_authorization": self.route_authorization,
            "execution_advisory": self.execution_advisory,
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


def cloud_fallback_execution_configured() -> bool:
    """Return whether the narrowly authorized Bedrock retry can execute."""

    return (
        _flag(
            getattr(settings, "prompt_facade_cloud_fallback_enabled", False),
            default=False,
        )
        and bool(
            _clean(getattr(settings, "prompt_facade_cloud_fallback_aws_region", ""))
        )
        and bool(
            _clean(
                getattr(
                    settings,
                    "prompt_facade_cloud_fallback_credentials_secret",
                    "",
                )
            )
        )
    )


def explicit_cloud_selection_execution_configured() -> bool:
    """Return whether an approved explicit GPT selection can use Mantle."""

    return bool(
        _clean(getattr(settings, "prompt_facade_cloud_fallback_aws_region", ""))
        and _clean(
            getattr(
                settings,
                "prompt_facade_explicit_cloud_mantle_api_key_secret",
                "",
            )
        )
    )


def capacity_model_for(requested_model: Any = "") -> tuple[str, str]:
    """Resolve a public Norman model alias for a non-invoking capacity probe."""

    requested = _clean(requested_model) or "norman-code"
    selected = MODEL_ALIASES.get(requested.lower())
    if selected is None:
        raise FacadeError(
            "Norman capacity is available only for supported local model aliases",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_capacity_model",
            param="model",
        )
    return requested, selected or ROUTE_POLICY_MODELS["router"]


def _local_failure_context(
    *,
    request_id: str,
    requested_model: str,
    selected_model: str,
    retryable: bool,
    capacity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "schema": "norman.local-gateway-error.v1",
        "request_id": request_id,
        "requested_model": requested_model or "norman-code",
        "selected_model": selected_model,
        "retryable": retryable,
        "cloud_fallback": False,
        **norllama_capacity.heavy_coding_capacity_policy(),
    }
    if capacity:
        context["capacity"] = dict(capacity)
    return context


def _safe_capacity_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(payload.get("norllama"))
    if _clean(raw.get("schema")) != "norllama.capacity.v1":
        return {}
    result: dict[str, Any] = {"schema": "norllama.capacity.v1"}
    for field, upper_bound in (
        ("active", 64),
        ("active_limit", 64),
        ("queue_depth", 1024),
        ("queue_limit", 1024),
        ("retry_after_seconds", 3600),
    ):
        try:
            result[field] = max(0, min(int(raw.get(field) or 0), upper_bound))
        except (TypeError, ValueError):
            continue
    return result


def _retry_after(headers: Mapping[str, Any] | None) -> str:
    values = {
        str(key).lower(): _clean(value) for key, value in dict(headers or {}).items()
    }
    try:
        return str(max(1, min(int(values.get("retry-after") or 5), 3600)))
    except (TypeError, ValueError):
        return "5"


def _classified_gateway_error(
    exc: Exception,
    *,
    request_id: str,
    requested_model: str,
    selected_model: str,
) -> FacadeError:
    status_code = 0
    response_headers: Mapping[str, Any] | None = None
    payload: Mapping[str, Any] = {}
    if isinstance(exc, norllama_gateway.NorllamaGatewayError):
        status_code = exc.status_code
        response_headers = exc.headers
        payload = exc.payload
    else:
        response = getattr(exc, "response", None)
        try:
            status_code = int(getattr(response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            status_code = 0
        response_headers = getattr(response, "headers", None)

    payload_error = _lower(_mapping(payload.get("error")).get("code")) or _lower(
        payload.get("error")
    )
    capacity = _safe_capacity_context(payload)
    if status_code == 422 and payload_error == "local_model_not_installed":
        return FacadeError(
            "Requested local model is not installed",
            status_code=422,
            error_type="invalid_request_error",
            code="local_model_not_installed",
            norman=_local_failure_context(
                request_id=request_id,
                requested_model=requested_model,
                selected_model=selected_model,
                retryable=False,
            ),
        )

    if payload_error in {"ollama_model_unavailable", "no_upstream_candidates"}:
        return FacadeError(
            "Local coding model is unavailable on eligible workers",
            status_code=503,
            error_type="server_error",
            code="local_model_unavailable",
            norman=_local_failure_context(
                request_id=request_id,
                requested_model=requested_model,
                selected_model=selected_model,
                retryable=True,
            ),
        )

    def local_error(
        *,
        message: str,
        status: int,
        code: str,
        retryable: bool,
        headers: Mapping[str, str] | None = None,
    ) -> FacadeError:
        return FacadeError(
            message,
            status_code=status,
            error_type="server_error",
            code=code,
            norman=_local_failure_context(
                request_id=request_id,
                requested_model=requested_model,
                selected_model=selected_model,
                retryable=retryable,
                capacity=capacity,
            ),
            headers=headers,
        )

    if status_code == 429:
        return local_error(
            message="Local coding capacity is exhausted",
            status=503,
            code="local_capacity_exhausted",
            retryable=True,
            headers={"Retry-After": _retry_after(response_headers)},
        )
    if status_code == 503:
        return local_error(
            message="Local coding capacity is unavailable",
            status=503,
            code="local_capacity_unavailable",
            retryable=True,
        )
    if status_code == 504 or isinstance(exc, (requests.Timeout, TimeoutError)):
        retry_after = norllama_capacity.LOCAL_MODEL_TIMEOUT_COOLDOWN_SECONDS
        return local_error(
            message=f"Local model request timed out; retry in {retry_after} seconds",
            status=504,
            code="local_model_timeout",
            retryable=True,
            headers={"Retry-After": str(retry_after)},
        )
    if status_code in {401, 403}:
        return local_error(
            message="Local model gateway authentication is unavailable",
            status=503,
            code="local_gateway_auth_failed",
            retryable=False,
        )
    if status_code >= 500:
        return local_error(
            message="Local model gateway is unavailable",
            status=503,
            code="local_gateway_unavailable",
            retryable=True,
        )
    if status_code >= 400:
        return local_error(
            message="Local model gateway returned an invalid response",
            status=502,
            code="local_gateway_bad_response",
            retryable=False,
        )
    if isinstance(exc, requests.RequestException):
        return local_error(
            message="Local model gateway is unreachable",
            status=503,
            code="local_gateway_unreachable",
            retryable=True,
        )
    if "empty response" in _lower(exc):
        return local_error(
            message="Local model returned empty content",
            status=502,
            code="empty_local_response",
            retryable=True,
        )
    return local_error(
        message="Local model gateway returned an invalid response",
        status=502,
        code="local_gateway_bad_response",
        retryable=True,
    )


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


def _previous_response_messages(
    previous_response_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    previous_response_id = _clean(previous_response_id)
    if not previous_response_id:
        return [], False
    with _RESPONSE_STATE_LOCK:
        state = dict(_RESPONSE_STATE.get(previous_response_id) or {})
    if not state:
        return [], False
    messages = _messages(state.get("messages"))
    for output_item in _messages(state.get("output_items")):
        if _clean(output_item.get("type")) != "function_call":
            continue
        function_call = {
            "arguments": output_item.get("arguments", ""),
            "call_id": _clean(output_item.get("call_id")),
            "name": _clean(output_item.get("name")),
            "type": "function_call",
        }
        messages.append(
            {
                "role": "assistant",
                "content": (
                    "Prior assistant function call "
                    "(replayed context only; do not execute): "
                    f"{json.dumps(function_call, ensure_ascii=True, sort_keys=True)}"
                ),
            }
        )
    output_text = _clean(state.get("output_text"))
    if output_text:
        messages.append({"role": "assistant", "content": output_text})
    return messages, True


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
    content = message.get("content")
    return content if isinstance(content, str) else _clean(content)


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
        return [
            {
                "role": "system",
                "content": (
                    "Norman facade tool contract: if a tool is required, respond "
                    "with JSON only in this shape: "
                    '{"tool_call":{"name":"tool_name","arguments":{}}}. '
                    "After every tool result, continue the task: use the next "
                    "available tool when it advances the request, then return "
                    "the final answer only after no further tool call is needed. "
                    "Do not stop merely to announce a discovered tool. "
                    "For an external Codex Apps capability, call tool_search first "
                    'with {"query":"what you need"}; do not call '
                    "mcp__codex_apps__..., list_mcp_resources, or "
                    "list_mcp_resource_templates directly. Once tool_search output "
                    "is in the conversation and its executable tool is declared, "
                    "use that tool directly; do not rediscover it. Otherwise "
                    "answer normally."
                ),
            }
        ]
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
                "After every tool result, continue the task: use the next "
                "available tool when it advances the request, then return the "
                "final answer only after no further tool call is needed. Do not "
                "stop merely to announce a discovered tool. Otherwise answer "
                "normally. Available tools: " + _json_dumps(compact)
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


def _responses_reasoning_advisory(payload: Mapping[str, Any]) -> dict[str, str]:
    """Validate Responses reasoning metadata without emulating hidden output."""

    if "reasoning" not in payload:
        return {}
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, Mapping):
        raise FacadeError(
            "Responses reasoning must be an object with an effort value",
            status_code=400,
            code="invalid_reasoning",
            param="reasoning",
        )
    unsupported = sorted(
        str(key) for key in reasoning if key not in {"context", "effort", "summary"}
    )
    if unsupported:
        raise FacadeError(
            "Unsupported Responses reasoning option: " + ", ".join(unsupported),
            status_code=501,
            error_type="unsupported_parameter",
            code="unsupported_reasoning_option",
            param=f"reasoning.{unsupported[0]}",
        )
    advisory: dict[str, str] = {}
    if "effort" in reasoning:
        effort = _lower(reasoning.get("effort"))
        if effort not in SUPPORTED_REASONING_EFFORTS:
            allowed = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
            raise FacadeError(
                f"Unsupported Responses reasoning effort: {effort or '<blank>'}. "
                f"Expected one of: {allowed}",
                status_code=400,
                code="invalid_reasoning_effort",
                param="reasoning.effort",
            )
        advisory["effort"] = effort
    if "summary" in reasoning:
        summary = _lower(reasoning.get("summary"))
        if summary not in SUPPORTED_REASONING_SUMMARIES:
            allowed = ", ".join(sorted(SUPPORTED_REASONING_SUMMARIES))
            raise FacadeError(
                f"Unsupported Responses reasoning summary: {summary or '<blank>'}. "
                f"Expected one of: {allowed}",
                status_code=400,
                code="invalid_reasoning_summary",
                param="reasoning.summary",
            )
        advisory["summary"] = summary
    if "context" in reasoning:
        context = _lower(reasoning.get("context"))
        if context not in SUPPORTED_REASONING_CONTEXTS:
            allowed = ", ".join(sorted(SUPPORTED_REASONING_CONTEXTS))
            raise FacadeError(
                f"Unsupported Responses reasoning context: {context or '<blank>'}. "
                f"Expected one of: {allowed}",
                status_code=400,
                code="invalid_reasoning_context",
                param="reasoning.context",
            )
        advisory["context"] = context
    if not advisory:
        raise FacadeError(
            "Responses reasoning must specify context, effort, or summary",
            status_code=400,
            code="invalid_reasoning",
            param="reasoning",
        )
    return advisory


def _responses_include_advisory(payload: Mapping[str, Any]) -> list[str]:
    """Validate legacy Responses include values that do not affect local execution."""

    if "include" not in payload:
        return []
    include = payload.get("include")
    if not isinstance(include, list) or not all(
        isinstance(value, str) for value in include
    ):
        raise FacadeError(
            "Responses include must be an array of strings",
            status_code=400,
            code="invalid_include",
            param="include",
        )
    requested = sorted({_lower(value) for value in include})
    unsupported = sorted(
        value for value in requested if value not in SUPPORTED_RESPONSES_INCLUDE_VALUES
    )
    if unsupported:
        raise FacadeError(
            "Unsupported Responses include value: " + ", ".join(unsupported),
            status_code=501,
            error_type="unsupported_parameter",
            code="unsupported_include_value",
            param="include",
        )
    return requested


def _responses_client_metadata_ignored(payload: Mapping[str, Any]) -> bool:
    """Validate opaque Codex metadata before deliberately discarding it."""

    if "client_metadata" not in payload:
        return False
    if not isinstance(payload.get("client_metadata"), Mapping):
        raise FacadeError(
            "Responses client_metadata must be an object",
            status_code=400,
            code="invalid_client_metadata",
            param="client_metadata",
        )
    return True


def _responses_store_requested(payload: Mapping[str, Any]) -> bool:
    """Validate the Responses persistence preference without exposing storage."""

    if "store" not in payload:
        return True
    store = payload.get("store")
    if not isinstance(store, bool):
        raise FacadeError(
            "Responses store must be a boolean",
            status_code=400,
            code="invalid_store",
            param="store",
        )
    return store


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
                function_call = {
                    "arguments": item.get("arguments", ""),
                    "call_id": _clean(item.get("call_id")),
                    "name": _clean(item.get("name")),
                    "type": "function_call",
                }
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            "Prior assistant function call "
                            "(replayed context only; do not execute): "
                            f"{json.dumps(function_call, ensure_ascii=True, sort_keys=True)}"
                        ),
                    }
                )
                continue
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


def _codex_apps_tool_search_query(name: str, arguments: Any) -> str:
    parsed_arguments = arguments
    if isinstance(arguments, str):
        try:
            parsed_arguments = json.loads(arguments)
        except (TypeError, ValueError):
            parsed_arguments = {}
    if isinstance(parsed_arguments, Mapping):
        query = _clean(parsed_arguments.get("query"))
        if query:
            return query
    capability = name.removeprefix(CODEX_APPS_TOOL_PREFIX)
    capability = capability.replace(".", " ").replace("_", " ")
    return "Find the executable Codex Apps tool for " + capability


def _mcp_resource_discovery_tool_search_query(arguments: Any) -> str:
    parsed_arguments = arguments
    if isinstance(arguments, str):
        try:
            parsed_arguments = json.loads(arguments)
        except (TypeError, ValueError):
            parsed_arguments = {}
    if isinstance(parsed_arguments, Mapping):
        server = _clean(parsed_arguments.get("server"))
        if server:
            return "Find the executable tool for the " + server + " MCP server"
    return "Find the executable tool for the requested connected MCP server"


def _extract_tool_calls(
    text: str,
    *,
    tools: list[dict[str, Any]],
    allow_implicit_tools: bool = False,
) -> list[dict[str, Any]]:
    names = _tool_names(tools)
    if not text or (not names and not allow_implicit_tools):
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
        if not name:
            continue
        arguments = raw.get("arguments", {})
        if name.startswith(CODEX_APPS_TOOL_PREFIX) and name not in names:
            # Codex Apps tools must be discovered before invocation. Some
            # local models emit a stale internal Apps name even when the
            # request includes a partial built-in tool registry.
            arguments = {"query": _codex_apps_tool_search_query(name, arguments)}
            name = IMPLICIT_TOOL_SEARCH_NAME
        elif name in MCP_RESOURCE_DISCOVERY_TOOL_NAMES and name not in names:
            # Resource listing is a client-internal discovery primitive. The
            # facade exposes tool_search as the supported discovery lifecycle.
            arguments = {"query": _mcp_resource_discovery_tool_search_query(arguments)}
            name = IMPLICIT_TOOL_SEARCH_NAME
        elif names and name not in names:
            continue
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
    output_item_id: str = "",
) -> list[dict[str, Any]]:
    if tool_calls:
        return [dict(item) for item in tool_calls]
    return [
        {
            "id": output_item_id or f"msg-norman-{uuid.uuid4().hex}",
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
    trusted_context: Mapping[str, Any],
) -> dict[str, Any]:
    messages = _messages(
        provider_payload.get("messages")
    ) or response_input_to_messages(provider_payload)
    reasoning_advisory = _responses_reasoning_advisory(provider_payload)
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
            "codex_reasoning_advisory": reasoning_advisory,
            **dict(trusted_context),
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
            "codex_reasoning_advisory": reasoning_advisory,
            **dict(trusted_context),
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
            "codex_reasoning_advisory": reasoning_advisory,
            **dict(trusted_context),
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
        # This facade only performs local text generation. These fields classify
        # a requested external action and stay advisory until a tool or session
        # executor reaches its own approval boundary.
        execution_advisory={
            "execution_allowed": _flag(
                recommendation.get("execution_allowed"), default=True
            ),
            "requires_approval": _flag(recommendation.get("requires_approval")),
        },
    )


@dataclass(frozen=True)
class AuthorizedChatInvocation:
    authorization: FacadeAuthorization
    max_tokens: int
    invocation_id: str
    trusted_context: dict[str, Any]
    reasoning_advisory: dict[str, str]
    correlation_headers: dict[str, str]


@dataclass(frozen=True)
class ExplicitCloudSelectionPlan:
    requested_alias: str
    provider: str
    model: str
    lane: str
    route_policy: dict[str, Any]
    route: NorllamaRoute


@dataclass(frozen=True)
class CloudFallbackPlan:
    requested_alias: str
    provider: str
    model: str
    lane: str
    route_policy: dict[str, Any]
    route: NorllamaRoute


def _looks_like_cloud_model_selection(requested_model: Any) -> bool:
    requested = _lower(requested_model)
    return requested.startswith("gpt-") or requested.startswith("openai.gpt-")


def _explicit_cloud_selection_plan(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
) -> ExplicitCloudSelectionPlan | None:
    """Build the one exact cloud route declared by the signed route policy."""

    requested_alias = _requested_model(provider_payload).lower()
    compiled_selection = explicit_cloud_selection_for_model(requested_alias)
    if compiled_selection is None:
        if _looks_like_cloud_model_selection(requested_alias):
            raise FacadeError(
                "The requested cloud model is not an approved Norman model alias",
                status_code=400,
                error_type="invalid_request_error",
                code="unsupported_model",
                param="model",
            )
        return None

    route_policy = _nested_dict(
        route_envelope,
        "norman_route",
        "decision",
        "metadata",
        "route_policy",
    )
    artifact = _mapping(route_policy.get("route_policy_artifact"))
    artifact_cloud_policy = _mapping(artifact.get("cloud_policy"))
    route_cloud_policy = _mapping(route_policy.get("cloud_policy"))
    artifact_selection = explicit_cloud_selection_for_model(
        requested_alias,
        cloud_policy=artifact_cloud_policy,
    )
    if (
        not artifact
        or artifact_selection != compiled_selection
        or route_cloud_policy != artifact_cloud_policy
    ):
        raise FacadeError(
            "Norman policy does not authorize the requested cloud model",
            status_code=403,
            error_type="policy_blocked",
            code="explicit_cloud_selection_not_authorized",
            param="model",
        )
    if not explicit_cloud_selection_execution_configured():
        raise FacadeError(
            "The selected cloud model is temporarily unavailable",
            status_code=503,
            error_type="server_error",
            code="explicit_cloud_selection_unavailable",
            param="model",
        )

    provider = compiled_selection["provider"]
    model = compiled_selection["model"]
    lane = compiled_selection["lane"]
    explicit_route_policy = {
        **route_policy,
        "provider": provider,
        "preferred_provider": provider,
        "provider_surface": provider,
        "model_proxy": provider,
        "model": model,
        "preferred_model": model,
        "lane": lane,
        # The adapter accepts this only with the exact signed selection marker.
        "allow_cloud_proxy": False,
        "cloud_policy": artifact_cloud_policy,
        "route_policy_artifact": artifact,
        "aws_region": _clean(
            getattr(settings, "prompt_facade_cloud_fallback_aws_region", "")
        ),
        "bedrock_mantle_api_key_secret": _clean(
            getattr(
                settings,
                "prompt_facade_explicit_cloud_mantle_api_key_secret",
                "",
            )
        ),
    }
    route = NorllamaRoute(
        lane=lane,
        provider=provider,
        provider_kind=provider,
        capability="chat",
        model=model,
        mode="cloud_proxy",
        local=False,
        cloud_proxy=True,
        tool_lane=False,
        requires_receipt=True,
        reason="facade explicit approved cloud model selection",
        attribution={"requested_alias": requested_alias},
    )
    return ExplicitCloudSelectionPlan(
        requested_alias=requested_alias,
        provider=provider,
        model=model,
        lane=lane,
        route_policy=explicit_route_policy,
        route=route,
    )


def _cloud_fallback_plan(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    local_error: FacadeError,
) -> CloudFallbackPlan | None:
    """Return the single allowed cloud retry route for a classified local failure."""

    requested_alias = _requested_model(provider_payload)
    if not _flag(local_error.norman.get("retryable")):
        return None
    route_policy = _nested_dict(
        route_envelope,
        "norman_route",
        "decision",
        "metadata",
        "route_policy",
    )
    artifact = _mapping(route_policy.get("route_policy_artifact"))
    fallbacks = _mapping(artifact.get("fallbacks"))
    provider = _lower(fallbacks.get("cloud_fallback_provider")).replace("_", "-")
    model = _clean(fallbacks.get("cloud_fallback_model"))
    lane = _lower(fallbacks.get("cloud_fallback_lane"))
    if (
        not artifact
        or not cloud_fallback_execution_configured()
        or not cloud_fallback_allowed_for_alias(
            requested_alias,
            fallback_policy=fallbacks,
        )
        or provider != CLOUD_FALLBACK_PROVIDER
        or model != CLOUD_FALLBACK_MODEL
        or lane != CLOUD_FALLBACK_LANE
    ):
        return None

    fallback_route_policy = {
        **route_policy,
        "provider": provider,
        "preferred_provider": provider,
        "provider_surface": provider,
        "model_proxy": provider,
        "model": model,
        "preferred_model": model,
        "lane": lane,
        "preferred_lane": lane,
        # This is a server-owned, narrowly authorized retry rather than a
        # general cloud proxy permission.
        "allow_cloud_proxy": False,
        "fallbacks": fallbacks,
        "route_policy_artifact": artifact,
        "aws_region": _clean(
            getattr(settings, "prompt_facade_cloud_fallback_aws_region", "")
        ),
        "aws_credentials_secret": _clean(
            getattr(
                settings,
                "prompt_facade_cloud_fallback_credentials_secret",
                "",
            )
        ),
    }
    route = NorllamaRoute(
        lane=lane,
        provider=provider,
        provider_kind=provider,
        capability="chat",
        model=model,
        mode="cloud_proxy",
        local=False,
        cloud_proxy=True,
        tool_lane=False,
        requires_receipt=True,
        reason=f"facade fallback after {local_error.code}",
        attribution={
            "fallback": "local_capacity_pre_output",
            "requested_alias": requested_alias,
            "local_failure_code": local_error.code,
        },
    )
    return CloudFallbackPlan(
        requested_alias=requested_alias,
        provider=provider,
        model=model,
        lane=lane,
        route_policy=fallback_route_policy,
        route=route,
    )


def _cloud_fallback_metadata(
    *,
    plan: CloudFallbackPlan,
    invocation: AuthorizedChatInvocation,
    local_error: FacadeError,
    state: str,
) -> dict[str, Any]:
    return {
        "schema": CLOUD_FALLBACK_SCHEMA,
        "state": state,
        "fallback_attempted": True,
        "local_failure_code": local_error.code,
        "fallback_provider": plan.provider,
        "fallback_model": plan.model,
        "request_id": invocation.invocation_id,
    }


def _cloud_fallback_marker(
    *,
    plan: CloudFallbackPlan,
    local_error: FacadeError,
) -> dict[str, Any]:
    return {
        "schema": CLOUD_FALLBACK_MARKER_SCHEMA,
        "attempt": 1,
        "requested_alias": plan.requested_alias,
        "local_failure_code": local_error.code,
    }


def _fallback_temperature(provider_payload: Mapping[str, Any]) -> float | None:
    value = provider_payload.get("temperature")
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _cloud_fallback_request(
    *,
    plan: CloudFallbackPlan,
    invocation: AuthorizedChatInvocation,
    messages: list[dict[str, Any]],
    provider_payload: Mapping[str, Any],
    local_error: FacadeError,
) -> ModelRequest:
    try:
        timeout_seconds = int(
            float(getattr(settings, "llm_provider_timeout_seconds", 45) or 45)
        )
    except (TypeError, ValueError):
        timeout_seconds = 45
    return ModelRequest(
        messages=messages,
        model=plan.model,
        route_key=plan.requested_alias,
        temperature=_fallback_temperature(provider_payload),
        budget=ModelBudget(
            max_model_calls=1,
            max_runtime_seconds=max(1, timeout_seconds),
            max_output_tokens=invocation.max_tokens,
        ),
        metadata={
            "request_id": invocation.invocation_id,
            "invocation_id": invocation.invocation_id,
            "norllama_task_kind": "chat",
            "execution_mode": "prompt_intermediary_openai_facade_cloud_fallback",
            "requested_model": plan.model,
            "route_selected_model": plan.model,
            "route_policy": plan.route_policy,
            "norllama_route": plan.route.as_dict(),
            "norman_facade_cloud_fallback": _cloud_fallback_marker(
                plan=plan,
                local_error=local_error,
            ),
            "codex_reasoning_advisory": invocation.reasoning_advisory,
            **invocation.trusted_context,
        },
    )


def _is_cloud_receipt_sensitive_key(value: Any) -> bool:
    key = _lower(value).replace("-", "_")
    return key in {
        "raw",
        "credentials",
        "cloud_credentials",
        "bedrock_credentials",
        "authorization",
        "api_key",
        "api_token",
        "access_key",
        "access_key_id",
        "secret",
        "secret_access_key",
        "session_token",
        "password",
    }


def _sanitize_cloud_receipt(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_cloud_receipt(item)
            for key, item in value.items()
            if not _is_cloud_receipt_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_sanitize_cloud_receipt(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_cloud_receipt(item) for item in value]
    return value


def _sanitized_cloud_receipts(
    result: ModelResult,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = _mapping(result.metadata)
    receipt = _sanitize_cloud_receipt(_mapping(metadata.get("norllama_receipt")))
    safe_receipt = _mapping(receipt)
    return safe_receipt, _mapping(safe_receipt.get("route_receipt"))


def _cloud_fallback_error(
    *,
    plan: CloudFallbackPlan,
    invocation: AuthorizedChatInvocation,
    local_error: FacadeError,
    code: str,
) -> FacadeError:
    message = (
        "Cloud fallback is not authorized"
        if code == "cloud_fallback_not_authorized"
        else "Cloud fallback could not complete"
    )
    cloud_fallback = _cloud_fallback_metadata(
        plan=plan,
        invocation=invocation,
        local_error=local_error,
        state="failed",
    )
    return FacadeError(
        message,
        status_code=503,
        error_type="server_error",
        code=code,
        norman={
            "cloud_fallback": cloud_fallback,
            "fallback_attempted": True,
            "local_failure_code": local_error.code,
        },
    )


def _log_cloud_fallback_failure(
    *,
    category: str,
    plan: CloudFallbackPlan,
    invocation: AuthorizedChatInvocation,
    error: Exception | None = None,
) -> None:
    logger.warning(
        "Norman cloud fallback failed category=%s request_id=%s "
        "fallback_provider=%s fallback_model=%s exception_class=%s",
        category,
        invocation.invocation_id,
        plan.provider,
        plan.model,
        type(error).__name__ if error is not None else "none",
    )


def _execute_cloud_fallback(
    *,
    plan: CloudFallbackPlan,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    invocation: AuthorizedChatInvocation,
    local_error: FacadeError,
) -> dict[str, Any]:
    """Run the one approved Bedrock fallback and return a facade chat response."""

    try:
        result = BedrockModelAdapter().invoke(
            _cloud_fallback_request(
                plan=plan,
                invocation=invocation,
                messages=messages,
                provider_payload=provider_payload,
                local_error=local_error,
            )
        )
    except Exception as exc:
        _log_cloud_fallback_failure(
            category="invoke_failed",
            plan=plan,
            invocation=invocation,
            error=exc,
        )
        raise _cloud_fallback_error(
            plan=plan,
            invocation=invocation,
            local_error=local_error,
            code="cloud_fallback_failed",
        ) from exc
    if result.stop_reason == "policy_blocked":
        _log_cloud_fallback_failure(
            category="policy_blocked",
            plan=plan,
            invocation=invocation,
        )
        raise _cloud_fallback_error(
            plan=plan,
            invocation=invocation,
            local_error=local_error,
            code="cloud_fallback_not_authorized",
        )
    if not result.text:
        _log_cloud_fallback_failure(
            category="empty_response",
            plan=plan,
            invocation=invocation,
        )
        raise _cloud_fallback_error(
            plan=plan,
            invocation=invocation,
            local_error=local_error,
            code="cloud_fallback_failed",
        )
    facade_receipt, route_receipt = _sanitized_cloud_receipts(result)
    usage = {
        "prompt_tokens": result.usage.input_tokens,
        "completion_tokens": result.usage.output_tokens,
        "total_tokens": result.usage.total_tokens,
    }
    return {
        "id": f"chatcmpl-norman-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model or plan.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "norman": {
            "schema": "norman.openai-compatible-facade.v1",
            "request_id": invocation.invocation_id,
            "route": dict(route_envelope),
            "gateway": invocation.trusted_context,
            "authorization": invocation.authorization.as_dict(),
            "local_execution": False,
            "cloud_forwarding": True,
            "cloud_fallback": _cloud_fallback_metadata(
                plan=plan,
                invocation=invocation,
                local_error=local_error,
                state="completed",
            ),
            "fallback_attempted": True,
            "local_failure_code": local_error.code,
            "fallback_provider": plan.provider,
            "fallback_model": plan.model,
            "streaming_mode": "buffered_sse"
            if provider_payload.get("stream")
            else "none",
            "norllama": {
                "target_worker": "",
                "gateway_selected_worker": "",
                "observed_worker": "",
                "observed_worker_source": "cloud_fallback",
                "headers": {},
            },
            "gateway_headers": {},
            "facade_receipt": facade_receipt,
            "route_receipt": route_receipt,
        },
    }


def _explicit_cloud_selection_metadata(
    *,
    plan: ExplicitCloudSelectionPlan,
    invocation: AuthorizedChatInvocation,
    state: str,
) -> dict[str, Any]:
    return {
        "schema": EXPLICIT_CLOUD_SELECTION_SCHEMA,
        "state": state,
        "requested_alias": plan.requested_alias,
        "provider": plan.provider,
        "model": plan.model,
        "lane": plan.lane,
        "request_id": invocation.invocation_id,
    }


def _explicit_cloud_selection_marker(
    *,
    plan: ExplicitCloudSelectionPlan,
) -> dict[str, Any]:
    return {
        "schema": EXPLICIT_CLOUD_SELECTION_MARKER_SCHEMA,
        "requested_alias": plan.requested_alias,
        "provider": plan.provider,
        "model": plan.model,
        "lane": plan.lane,
    }


def _explicit_cloud_selection_request(
    *,
    plan: ExplicitCloudSelectionPlan,
    invocation: AuthorizedChatInvocation,
    messages: list[dict[str, Any]],
    provider_payload: Mapping[str, Any],
) -> ModelRequest:
    try:
        timeout_seconds = int(
            float(getattr(settings, "llm_provider_timeout_seconds", 45) or 45)
        )
    except (TypeError, ValueError):
        timeout_seconds = 45
    return ModelRequest(
        messages=messages,
        model=plan.model,
        route_key=plan.requested_alias,
        temperature=_fallback_temperature(provider_payload),
        budget=ModelBudget(
            max_model_calls=1,
            max_runtime_seconds=max(1, timeout_seconds),
            max_output_tokens=invocation.max_tokens,
        ),
        metadata={
            "request_id": invocation.invocation_id,
            "invocation_id": invocation.invocation_id,
            "norllama_task_kind": "chat",
            "execution_mode": "prompt_intermediary_openai_facade_explicit_cloud",
            "requested_model": plan.model,
            "route_selected_model": plan.model,
            "route_policy": plan.route_policy,
            "norllama_route": plan.route.as_dict(),
            "norman_facade_explicit_cloud_selection": (
                _explicit_cloud_selection_marker(plan=plan)
            ),
            "codex_reasoning_advisory": invocation.reasoning_advisory,
            **invocation.trusted_context,
        },
    )


def _explicit_cloud_selection_error(
    *,
    plan: ExplicitCloudSelectionPlan,
    invocation: AuthorizedChatInvocation,
    code: str,
) -> FacadeError:
    message = (
        "The selected cloud model is not authorized"
        if code == "explicit_cloud_selection_not_authorized"
        else "The selected cloud model could not complete"
    )
    return FacadeError(
        message,
        status_code=503,
        error_type="server_error",
        code=code,
        norman={
            "explicit_cloud_selection": _explicit_cloud_selection_metadata(
                plan=plan,
                invocation=invocation,
                state="failed",
            )
        },
    )


def _execute_explicit_cloud_selection(
    *,
    plan: ExplicitCloudSelectionPlan,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    invocation: AuthorizedChatInvocation,
) -> dict[str, Any]:
    """Run a user-selected cloud model without probing local capacity."""

    try:
        result = BedrockModelAdapter().invoke(
            _explicit_cloud_selection_request(
                plan=plan,
                invocation=invocation,
                messages=messages,
                provider_payload=provider_payload,
            )
        )
    except Exception as exc:
        logger.warning(
            "Norman explicit cloud selection failed request_id=%s provider=%s "
            "model=%s exception_class=%s",
            invocation.invocation_id,
            plan.provider,
            plan.model,
            type(exc).__name__,
        )
        raise _explicit_cloud_selection_error(
            plan=plan,
            invocation=invocation,
            code="explicit_cloud_selection_failed",
        ) from exc
    if result.stop_reason == "policy_blocked":
        raise _explicit_cloud_selection_error(
            plan=plan,
            invocation=invocation,
            code="explicit_cloud_selection_not_authorized",
        )
    if not result.text:
        raise _explicit_cloud_selection_error(
            plan=plan,
            invocation=invocation,
            code="explicit_cloud_selection_failed",
        )
    facade_receipt, route_receipt = _sanitized_cloud_receipts(result)
    usage = {
        "prompt_tokens": result.usage.input_tokens,
        "completion_tokens": result.usage.output_tokens,
        "total_tokens": result.usage.total_tokens,
    }
    return {
        "id": f"chatcmpl-norman-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model or plan.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "norman": {
            "schema": "norman.openai-compatible-facade.v1",
            "request_id": invocation.invocation_id,
            "route": dict(route_envelope),
            "gateway": invocation.trusted_context,
            "authorization": invocation.authorization.as_dict(),
            "local_execution": False,
            "cloud_forwarding": True,
            "explicit_cloud_selection": _explicit_cloud_selection_metadata(
                plan=plan,
                invocation=invocation,
                state="completed",
            ),
            "streaming_mode": "buffered_sse"
            if provider_payload.get("stream")
            else "none",
            "norllama": {
                "target_worker": "",
                "gateway_selected_worker": "",
                "observed_worker": "",
                "observed_worker_source": "explicit_cloud_selection",
                "headers": {},
            },
            "gateway_headers": {},
            "facade_receipt": facade_receipt,
            "route_receipt": route_receipt,
        },
    }


def _prepare_explicit_cloud_selection_invocation(
    *,
    plan: ExplicitCloudSelectionPlan,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    request_id: str,
) -> AuthorizedChatInvocation:
    recommendation = _nested_dict(route_envelope, "norman_route", "recommendation")
    artifact = _mapping(plan.route_policy.get("route_policy_artifact"))
    trusted_context = _mapping(route_envelope.get("trusted_gateway_context"))
    reasoning_advisory = _responses_reasoning_advisory(provider_payload)
    invocation_id = request_id or f"norman-openai-facade-{uuid.uuid4().hex}"
    authorization = FacadeAuthorization(
        allowed=True,
        model=plan.model,
        reason="explicit_cloud_selection_authorized",
        route=dict(route_envelope),
        route_authorization={
            "schema": "norman.facade-explicit-cloud-selection.authorization.v1",
            "allowed": True,
            "policy_id": _clean(artifact.get("policy_id")),
            "policy_hash": _clean(artifact.get("policy_hash")),
            "reason": "adapter_authorization_required_before_egress",
        },
        execution_advisory={
            "execution_allowed": _flag(
                recommendation.get("execution_allowed"), default=True
            ),
            "requires_approval": _flag(recommendation.get("requires_approval")),
        },
    )
    correlation_headers = {
        "X-Request-Id": invocation_id,
        "X-Norman-Execution-Mode": ("prompt_intermediary_openai_facade_explicit_cloud"),
        "X-Norman-Phase": "chat",
        "X-Norman-Route-Authority": "prompt_intermediary",
        "X-Norman-Request-Production-Eligible": "false",
    }
    if _clean(trusted_context.get("gateway_route")):
        correlation_headers.update(
            {
                "X-Norman-Gateway-Route": _clean(trusted_context.get("gateway_route")),
                "X-Norman-Source-Tui": _clean(trusted_context.get("source_tui")),
                "X-Norman-Policy-Scope": _clean(trusted_context.get("policy_scope")),
            }
        )
    return AuthorizedChatInvocation(
        authorization=authorization,
        max_tokens=_positive_int(
            provider_payload.get("max_completion_tokens")
            or provider_payload.get("max_output_tokens")
            or provider_payload.get("max_tokens"),
            1024,
        ),
        invocation_id=invocation_id,
        trusted_context=trusted_context,
        reasoning_advisory=reasoning_advisory,
        correlation_headers=correlation_headers,
    )


def _prepare_authorized_chat_invocation(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    request_id: str,
) -> AuthorizedChatInvocation:
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
    trusted_context = _mapping(route_envelope.get("trusted_gateway_context"))
    reasoning_advisory = _responses_reasoning_advisory(provider_payload)
    correlation_headers = {
        "X-Request-Id": invocation_id,
        "X-Norman-Execution-Mode": "prompt_intermediary_openai_facade",
        "X-Norman-Phase": "chat",
        "X-Norman-Route-Authority": "prompt_intermediary",
        "X-Norman-Request-Production-Eligible": "false",
    }
    if _clean(trusted_context.get("gateway_route")):
        correlation_headers.update(
            {
                "X-Norman-Gateway-Route": _clean(trusted_context.get("gateway_route")),
                "X-Norman-Source-Tui": _clean(trusted_context.get("source_tui")),
                "X-Norman-Policy-Scope": _clean(trusted_context.get("policy_scope")),
            }
        )
    if "effort" in reasoning_advisory:
        correlation_headers["X-Norman-Requested-Reasoning-Effort"] = reasoning_advisory[
            "effort"
        ]
    if "context" in reasoning_advisory:
        correlation_headers["X-Norman-Requested-Reasoning-Context"] = (
            reasoning_advisory["context"]
        )
    return AuthorizedChatInvocation(
        authorization=authorization,
        max_tokens=max_tokens,
        invocation_id=invocation_id,
        trusted_context=trusted_context,
        reasoning_advisory=reasoning_advisory,
        correlation_headers=correlation_headers,
    )


def _complete_authorized_chat(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    invocation: AuthorizedChatInvocation,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    authorization = invocation.authorization
    invocation_id = invocation.invocation_id
    trusted_context = invocation.trusted_context
    reasoning_advisory = invocation.reasoning_advisory
    text = _choice_text(result)
    if not text:
        raise FacadeError(
            "Local model returned empty content",
            status_code=502,
            error_type="server_error",
            code="empty_local_response",
            norman=_local_failure_context(
                request_id=invocation_id,
                requested_model=_requested_model(provider_payload),
                selected_model=authorization.model,
                retryable=True,
            ),
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
        trusted_context=trusted_context,
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
            "gateway": trusted_context,
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


def _execute_authorized_chat(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    request_id: str,
) -> dict[str, Any]:
    explicit_cloud_plan = _explicit_cloud_selection_plan(
        provider_payload=provider_payload,
        route_envelope=route_envelope,
    )
    if explicit_cloud_plan is not None:
        invocation = _prepare_explicit_cloud_selection_invocation(
            plan=explicit_cloud_plan,
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            request_id=request_id,
        )
        return _execute_explicit_cloud_selection(
            plan=explicit_cloud_plan,
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            messages=messages,
            invocation=invocation,
        )

    invocation = _prepare_authorized_chat_invocation(
        provider_payload=provider_payload,
        route_envelope=route_envelope,
        request_id=request_id,
    )
    try:
        result = norllama_gateway.invoke_text_chat(
            messages=messages,
            model=invocation.authorization.model,
            base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
            api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
            max_tokens=invocation.max_tokens,
            timeout_seconds=float(
                getattr(settings, "llm_provider_timeout_seconds", 45)
            ),
            correlation_headers=invocation.correlation_headers,
        )
    except (
        norllama_gateway.NorllamaGatewayError,
        requests.RequestException,
        RuntimeError,
        TimeoutError,
    ) as exc:
        local_error = _classified_gateway_error(
            exc,
            request_id=invocation.invocation_id,
            requested_model=_requested_model(provider_payload),
            selected_model=invocation.authorization.model,
        )
        plan = _cloud_fallback_plan(
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            local_error=local_error,
        )
        if plan is None:
            raise local_error from exc
        return _execute_cloud_fallback(
            plan=plan,
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            messages=messages,
            invocation=invocation,
            local_error=local_error,
        )
    try:
        return _complete_authorized_chat(
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            messages=messages,
            invocation=invocation,
            result=result,
        )
    except FacadeError as local_error:
        plan = _cloud_fallback_plan(
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            local_error=local_error,
        )
        if plan is None:
            raise
        return _execute_cloud_fallback(
            plan=plan,
            provider_payload=provider_payload,
            route_envelope=route_envelope,
            messages=messages,
            invocation=invocation,
            local_error=local_error,
        )


def _start_authorized_chat_stream(
    *,
    provider_payload: Mapping[str, Any],
    route_envelope: Mapping[str, Any],
    messages: list[dict[str, Any]],
    request_id: str,
) -> tuple[
    AuthorizedChatInvocation,
    norllama_gateway.NorllamaTextStream | None,
    FacadeError | None,
]:
    invocation = _prepare_authorized_chat_invocation(
        provider_payload=provider_payload,
        route_envelope=route_envelope,
        request_id=request_id,
    )
    try:
        stream = norllama_gateway.invoke_text_chat_stream(
            messages=messages,
            model=invocation.authorization.model,
            base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
            api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
            max_tokens=invocation.max_tokens,
            timeout_seconds=float(
                getattr(settings, "llm_provider_timeout_seconds", 45)
            ),
            correlation_headers=invocation.correlation_headers,
        )
    except (
        norllama_gateway.NorllamaGatewayError,
        requests.RequestException,
        RuntimeError,
        TimeoutError,
    ) as exc:
        return (
            invocation,
            None,
            _classified_gateway_error(
                exc,
                request_id=invocation.invocation_id,
                requested_model=_requested_model(provider_payload),
                selected_model=invocation.authorization.model,
            ),
        )
    return invocation, stream, None


def execute_openai_chat_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
    trusted_context: Mapping[str, Any] | None = None,
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
        trusted_context=trusted_context,
    )
    return _execute_authorized_chat(
        provider_payload=provider_payload,
        route_envelope=route_envelope,
        messages=messages,
        request_id=request_id,
    )


@dataclass(frozen=True)
class PreparedResponsesExecution:
    provider_payload: dict[str, Any]
    route_payload: dict[str, Any]
    route_envelope: dict[str, Any]
    messages: list[dict[str, Any]]
    previous_messages: list[dict[str, Any]]
    history_replayed: bool
    client_metadata_ignored: bool
    store_requested: bool


def _prepare_responses_execution(
    payload: Mapping[str, Any],
    *,
    trusted_context: Mapping[str, Any] | None = None,
) -> PreparedResponsesExecution:
    _validate_supported_fields(payload, supported_fields=SUPPORTED_RESPONSES_FIELDS)
    provider_payload = _prepare_payload(payload)
    reasoning_advisory = _responses_reasoning_advisory(provider_payload)
    include_advisory = _responses_include_advisory(provider_payload)
    client_metadata_ignored = _responses_client_metadata_ignored(provider_payload)
    store_requested = _responses_store_requested(provider_payload)
    provider_payload.pop("client_metadata", None)
    provider_payload.pop("store", None)
    if reasoning_advisory:
        provider_payload["reasoning"] = reasoning_advisory
    if include_advisory:
        provider_payload["include"] = include_advisory
    previous_messages, history_replayed = _previous_response_messages(
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
        trusted_context=trusted_context,
    )
    return PreparedResponsesExecution(
        provider_payload=provider_payload,
        route_payload=route_payload,
        route_envelope=route_envelope,
        messages=messages,
        previous_messages=previous_messages,
        history_replayed=history_replayed,
        client_metadata_ignored=client_metadata_ignored,
        store_requested=store_requested,
    )


def _responses_response_from_chat(
    chat_response: Mapping[str, Any],
    *,
    prepared: PreparedResponsesExecution,
    response_id: str = "",
    created_at: int | None = None,
    output_item_id: str = "",
) -> dict[str, Any]:
    provider_payload = prepared.provider_payload
    chat_response = dict(chat_response)
    text = _choice_text(chat_response)
    tools = _tools(provider_payload)
    tool_calls = _extract_tool_calls(
        text,
        tools=tools,
        # Some Codex TUI request forms keep their executable tool registry
        # client-side and omit a top-level Responses tools list. The TUI still
        # validates the returned call before it can execute anything.
        allow_implicit_tools=not bool(_tool_names(tools)),
    )
    output_items = _response_output_items(
        text=text,
        tool_calls=tool_calls,
        output_item_id=output_item_id,
    )
    output_text = "" if tool_calls else text
    response_id = response_id or f"resp-norman-{uuid.uuid4().hex}"
    created = created_at or int(time.time())
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
                "history_replayed": prepared.history_replayed,
                "history_state": (
                    "not_requested"
                    if not _clean(provider_payload.get("previous_response_id"))
                    else "replayed"
                    if prepared.history_replayed
                    else "unavailable"
                ),
                "tools_declared": len(tools),
                "tool_calls_returned": len(tool_calls),
                "tool_call_mode": (
                    "explicit_json_envelope"
                    if _tool_names(tools)
                    else "implicit_json_envelope"
                    if tool_calls
                    else "none"
                ),
                "structured_output_requested": bool(
                    _mapping(provider_payload.get("text")).get("format")
                ),
                "reasoning_advisory": _responses_reasoning_advisory(provider_payload),
                "include_advisory": _responses_include_advisory(provider_payload),
                "client_metadata_ignored": prepared.client_metadata_ignored,
                "store_requested": prepared.store_requested,
            },
        },
    }
    if prepared.store_requested:
        _store_response_state(
            response_id,
            messages=prepared.messages,
            output_text=output_text,
            output_items=output_items,
        )
    return response


class FacadeResponsesStream:
    """An admitted local response stream with final facade response assembly."""

    def __init__(
        self,
        *,
        prepared: PreparedResponsesExecution,
        invocation: AuthorizedChatInvocation,
        stream: norllama_gateway.NorllamaTextStream | None,
        pending_local_error: FacadeError | None = None,
        explicit_cloud_plan: ExplicitCloudSelectionPlan | None = None,
    ) -> None:
        self.prepared = prepared
        self.invocation = invocation
        self.stream = stream
        self.pending_local_error = pending_local_error
        self.explicit_cloud_plan = explicit_cloud_plan
        self.response_id = f"resp-norman-{uuid.uuid4().hex}"
        self.created_at = int(time.time())
        self.output_item_id = f"msg-norman-{uuid.uuid4().hex}"
        self._stream_admission = self._admission_metadata_from_headers()
        self._cloud_chat_response: dict[str, Any] | None = None
        self._cloud_fallback_attempted = False

    @property
    def model(self) -> str:
        if self._cloud_chat_response is not None:
            return (
                _clean(self._cloud_chat_response.get("model"))
                or self.invocation.authorization.model
            )
        if self.stream is not None:
            return self.stream.model or self.invocation.authorization.model
        return self.invocation.authorization.model

    def _admission_metadata_from_headers(self) -> dict[str, Any]:
        if self.stream is None:
            return {}
        headers = self.stream.headers
        admission = _clean(headers.get("x-norllama-admission"))
        if admission not in {"immediate", "queued"}:
            return {}
        metadata: dict[str, Any] = {
            "schema": "norman.stream-admission.v1",
            "state": admission,
        }
        for header, field in (
            ("x-norllama-queue-wait-ms", "queue_wait_ms"),
            ("x-norllama-queue-depth", "queue_depth"),
            ("x-norllama-queue-limit", "queue_limit"),
            ("x-norllama-active", "active"),
            ("x-norllama-active-limit", "active_limit"),
        ):
            try:
                value = int(headers.get(header) or 0)
            except (TypeError, ValueError):
                continue
            metadata[field] = max(0, min(value, 3600000))
        return metadata

    def admission_metadata(self) -> dict[str, Any]:
        return dict(self._stream_admission)

    def update_admission_metadata(self, frame: Mapping[str, Any]) -> None:
        if _clean(frame.get("schema")) != "norllama.stream-admission.v1":
            return
        event = _clean(frame.get("event"))
        state = _clean(frame.get("state"))
        if event == "queued":
            state = "queued"
        elif event == "admitted":
            state = "admitted"
        if state not in {"queued", "admitted", "immediate"}:
            return
        metadata: dict[str, Any] = {
            "schema": "norman.stream-admission.v1",
            "state": state,
        }
        for field in (
            "queue_wait_ms",
            "queue_depth",
            "queue_limit",
            "active",
            "active_limit",
            "retry_after_seconds",
        ):
            try:
                value = int(frame.get(field) or 0)
            except (TypeError, ValueError):
                continue
            metadata[field] = max(0, min(value, 3600000))
        self._stream_admission = metadata

    def _empty_local_response_error(self) -> FacadeError:
        return FacadeError(
            "Local model returned empty content",
            status_code=502,
            error_type="server_error",
            code="empty_local_response",
            norman=_local_failure_context(
                request_id=self.invocation.invocation_id,
                requested_model=_requested_model(self.prepared.route_payload),
                selected_model=self.invocation.authorization.model,
                retryable=True,
            ),
        )

    def _cloud_fallback_events(self, local_error: FacadeError):
        plan = _cloud_fallback_plan(
            provider_payload=self.prepared.route_payload,
            route_envelope=self.prepared.route_envelope,
            local_error=local_error,
        )
        if plan is None or self._cloud_fallback_attempted:
            raise local_error
        self._cloud_fallback_attempted = True
        if self.stream is not None:
            self.stream.close()
        yield {
            "type": "cloud_fallback",
            "cloud_fallback": _cloud_fallback_metadata(
                plan=plan,
                invocation=self.invocation,
                local_error=local_error,
                state="started",
            ),
        }
        self._cloud_chat_response = _execute_cloud_fallback(
            plan=plan,
            provider_payload=self.prepared.route_payload,
            route_envelope=self.prepared.route_envelope,
            messages=self.prepared.messages,
            invocation=self.invocation,
            local_error=local_error,
        )
        text = _choice_text(self._cloud_chat_response)
        if text:
            yield {"type": "text", "text": text}

    def iter_events(self):
        if self.explicit_cloud_plan is not None:
            yield {
                "type": "explicit_cloud_selection",
                "explicit_cloud_selection": _explicit_cloud_selection_metadata(
                    plan=self.explicit_cloud_plan,
                    invocation=self.invocation,
                    state="started",
                ),
            }
            self._cloud_chat_response = _execute_explicit_cloud_selection(
                plan=self.explicit_cloud_plan,
                provider_payload=self.prepared.route_payload,
                route_envelope=self.prepared.route_envelope,
                messages=self.prepared.messages,
                invocation=self.invocation,
            )
            text = _choice_text(self._cloud_chat_response)
            if text:
                yield {"type": "text", "text": text}
            return
        if self.pending_local_error is not None:
            yield from self._cloud_fallback_events(self.pending_local_error)
            return
        if self.stream is None:
            raise RuntimeError("Local response stream was not initialized")

        emitted_local_text = False
        try:
            for event in self.stream.iter_events():
                if event.get("type") == "admission":
                    admission = event.get("admission")
                    if isinstance(admission, Mapping):
                        self.update_admission_metadata(admission)
                if (
                    event.get("type") == "text"
                    and isinstance(event.get("text"), str)
                    and event["text"]
                ):
                    emitted_local_text = True
                yield event
        except Exception as exc:
            local_error = self.classify_error(exc)
            if emitted_local_text:
                raise local_error from exc
            yield from self._cloud_fallback_events(local_error)
            return

        if not emitted_local_text:
            yield from self._cloud_fallback_events(self._empty_local_response_error())

    def iter_text(self):
        for event in self.iter_events():
            if event.get("type") == "text":
                fragment = event.get("text")
                if isinstance(fragment, str) and fragment:
                    yield fragment

    def complete(self, text: str) -> dict[str, Any]:
        if self._cloud_chat_response is not None:
            chat_response = dict(self._cloud_chat_response)
        else:
            if self.stream is None:
                raise RuntimeError("Local response stream was not initialized")
            chat_response = _complete_authorized_chat(
                provider_payload=self.prepared.route_payload,
                route_envelope=self.prepared.route_envelope,
                messages=self.prepared.messages,
                invocation=self.invocation,
                result=self.stream.result(text),
            )
        norman = _mapping(chat_response.get("norman"))
        if self._cloud_chat_response is None:
            norman["streaming_mode"] = "incremental_sse"
        admission = self.admission_metadata()
        if admission:
            norman["stream_admission"] = admission
        chat_response["norman"] = norman
        return _responses_response_from_chat(
            chat_response,
            prepared=self.prepared,
            response_id=self.response_id,
            created_at=self.created_at,
            output_item_id=self.output_item_id,
        )

    def classify_error(self, exc: Exception) -> FacadeError:
        if isinstance(exc, FacadeError):
            return exc
        return _classified_gateway_error(
            exc,
            request_id=self.invocation.invocation_id,
            requested_model=_requested_model(self.prepared.route_payload),
            selected_model=self.invocation.authorization.model,
        )

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()


def execute_openai_responses_facade(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
    trusted_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the OpenAI Responses local text subset with one route decision."""

    prepared = _prepare_responses_execution(
        payload,
        trusted_context=trusted_context,
    )
    chat_response = _execute_authorized_chat(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        messages=prepared.messages,
        request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
    )
    return _responses_response_from_chat(
        chat_response,
        prepared=prepared,
    )


def open_openai_responses_stream(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
    trusted_context: Mapping[str, Any] | None = None,
) -> FacadeResponsesStream:
    """Authorize and open the local upstream before returning a response stream."""

    prepared = _prepare_responses_execution(
        payload,
        trusted_context=trusted_context,
    )
    explicit_cloud_plan = _explicit_cloud_selection_plan(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
    )
    if explicit_cloud_plan is not None:
        invocation = _prepare_explicit_cloud_selection_invocation(
            plan=explicit_cloud_plan,
            provider_payload=prepared.route_payload,
            route_envelope=prepared.route_envelope,
            request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
        )
        return FacadeResponsesStream(
            prepared=prepared,
            invocation=invocation,
            stream=None,
            explicit_cloud_plan=explicit_cloud_plan,
        )
    invocation, stream, pending_local_error = _start_authorized_chat_stream(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        messages=prepared.messages,
        request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
    )
    return FacadeResponsesStream(
        prepared=prepared,
        invocation=invocation,
        stream=stream,
        pending_local_error=pending_local_error,
    )


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
