from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Mapping

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
UNSUPPORTED_RESPONSES_SEMANTIC_FIELDS = frozenset(
    {
        "background",
        "conversation",
        "modalities",
        "response_format",
        "stream_options",
    }
)
SUPPORTED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
SUPPORTED_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed", "none"})
SUPPORTED_REASONING_CONTEXTS = frozenset({"auto", "current_turn", "all_turns"})
SUPPORTED_RESPONSES_INCLUDE_VALUES = frozenset({"reasoning.encrypted_content"})
DEFAULT_FACADE_TOKENS = 16384
MAX_FACADE_TOKENS = 32768
MAX_RESPONSE_STATE = 200
MAX_REPLAYED_HISTORY_CHARS = 96_000
MAX_REPLAYED_HISTORY_ANCHOR_CHARS = 16_000
MAX_REPLAYED_TOOL_OUTPUT_CHARS = 12_000
MAX_REPLAYED_TOOL_OUTPUTS = 2
CLOUD_FALLBACK_SCHEMA = "norman.cloud-fallback.v1"
CLOUD_FALLBACK_MARKER_SCHEMA = "norman.facade-cloud-fallback.v1"
CLOUD_FALLBACK_PROVIDER = "aws-bedrock"
CLOUD_FALLBACK_MODEL = CLOUD_FALLBACK_BEDROCK_MODEL
CLOUD_FALLBACK_LANE = "coder"
EXPLICIT_CLOUD_SELECTION_SCHEMA = "norman.explicit-cloud-selection.v1"
EXPLICIT_CLOUD_SELECTION_MARKER_SCHEMA = "norman.facade-explicit-cloud-selection.v1"
LEGACY_REPLAYED_FUNCTION_CALL_PREFIX = (
    "Prior assistant function call (replayed context only; do not execute): "
)
TOOL_CHAIN_SCHEMA = "norman.responses-tool-chain.v1"
TOOL_CONTRACT_CONTEXT_MARKER = "_norman_responses_context"
TOOL_CONTRACT_CONTEXT_KIND = "tool_contract"
REPLAYED_CONTEXT_OMITTED = (
    "\n[Norman omitted older replayed context to fit the local model window.]\n"
)
REPLAYED_TOOL_OUTPUT_OMITTED = (
    "[Norman omitted older replayed tool output to fit the local model window.]"
)
TOOL_OUTPUT_FAILURE_MARKERS = (
    "access denied",
    "permission denied",
    "unauthorized",
    "forbidden",
    "execution_not_allowed",
    "tool failed",
    "failed to execute",
)
CLOUD_STREAM_HEARTBEAT_INTERVAL_SECONDS = 5.0
CLOUD_STREAM_MAX_ACTIVE_INVOCATIONS = 4
LOCAL_STREAM_OPEN_HEARTBEAT_INTERVAL_SECONDS = 5.0
LOCAL_STREAM_OPEN_MAX_ACTIVE_INVOCATIONS = 4
logger = logging.getLogger(__name__)
MODEL_ALIASES = {
    # Legacy local aliases remain available outside the Terra-only Codex work route.
    "norman-code": ROUTE_POLICY_MODELS["coding_operator"],
    "norman-code-governed": ROUTE_POLICY_MODELS["coding_operator"],
    "norman-fast": ROUTE_POLICY_MODELS["router"],
    "norman-local": "",
    "norman-reasoning": ROUTE_POLICY_MODELS["router"],
}
TRANSPARENT_BRIDGE_MODE = "transparent"
GOVERNED_BRIDGE_MODE = "governed"
GOVERNED_BRIDGE_MODEL_ALIASES = frozenset({"norman-code-governed"})
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
_CLOUD_STREAM_WORKER_SLOTS = threading.BoundedSemaphore(
    CLOUD_STREAM_MAX_ACTIVE_INVOCATIONS
)
_LOCAL_STREAM_OPEN_WORKER_SLOTS = threading.BoundedSemaphore(
    LOCAL_STREAM_OPEN_MAX_ACTIVE_INVOCATIONS
)


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


def _run_bounded_invocation_with_progress(
    *,
    operation: Callable[[], Any],
    progress_event: Callable[[str, int], dict[str, Any]],
    worker_slots: threading.BoundedSemaphore,
    worker_name: str,
    heartbeat_interval_seconds: float,
):
    """Run a bounded blocking operation while keeping an SSE response live."""

    started_at = time.monotonic()
    interval_seconds = max(0.001, float(heartbeat_interval_seconds))
    acquired = worker_slots.acquire(blocking=False)
    while not acquired:
        yield progress_event(
            "queued",
            max(0, int((time.monotonic() - started_at) * 1000)),
        )
        acquired = worker_slots.acquire(timeout=interval_seconds)

    completed = threading.Event()
    outcome: dict[str, Any] = {}
    errors: list[Exception] = []

    def run_operation() -> None:
        try:
            outcome["result"] = operation()
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()
            worker_slots.release()

    worker = threading.Thread(
        target=run_operation,
        name=worker_name,
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        worker_slots.release()
        raise

    yield progress_event(
        "in_progress",
        max(0, int((time.monotonic() - started_at) * 1000)),
    )
    while not completed.wait(interval_seconds):
        yield progress_event(
            "in_progress",
            max(0, int((time.monotonic() - started_at) * 1000)),
        )
    if errors:
        raise errors[0]
    return outcome["result"]


def _run_cloud_invocation_with_progress(
    *,
    operation: Callable[[], dict[str, Any]],
    progress_event: Callable[[str, int], dict[str, Any]],
):
    """Run one bounded cloud call while keeping an SSE response live."""

    return (
        yield from _run_bounded_invocation_with_progress(
            operation=operation,
            progress_event=progress_event,
            worker_slots=_CLOUD_STREAM_WORKER_SLOTS,
            worker_name="norman-cloud-stream",
            heartbeat_interval_seconds=CLOUD_STREAM_HEARTBEAT_INTERVAL_SECONDS,
        )
    )


def _run_local_stream_open_with_progress(
    *,
    operation: Callable[[], norllama_gateway.NorllamaTextStream],
    progress_event: Callable[[str, int], dict[str, Any]],
):
    """Open a local stream in a bounded worker while keeping SSE live."""

    return (
        yield from _run_bounded_invocation_with_progress(
            operation=operation,
            progress_event=progress_event,
            worker_slots=_LOCAL_STREAM_OPEN_WORKER_SLOTS,
            worker_name="norman-local-stream-open",
            heartbeat_interval_seconds=LOCAL_STREAM_OPEN_HEARTBEAT_INTERVAL_SECONDS,
        )
    )


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
    function_call_items: Mapping[str, Mapping[str, Any]],
    response_function_call_items: list[Mapping[str, Any]],
    tool_outputs: set[tuple[str, str]],
    ephemeral: bool,
    native_response_output_items: list[Mapping[str, Any]] | None = None,
) -> None:
    if not response_id:
        return
    stored_messages = [dict(message) for message in messages]
    native_output_items = _messages(native_response_output_items)
    if not native_output_items:
        if output_text:
            stored_messages.append({"role": "assistant", "content": output_text})
        for function_call in response_function_call_items:
            stored_messages.append(_function_call_context_message(function_call))
    stored_tool_outputs = [
        {"call_id": call_id, "output": output}
        for call_id, output in sorted(tool_outputs)
    ]
    with _RESPONSE_STATE_LOCK:
        _RESPONSE_STATE[response_id] = {
            "messages": stored_messages,
            "output_text": output_text,
            "messages_include_response_output": True,
            "function_calls": [
                dict(function_call) for function_call in function_call_items.values()
            ],
            "native_response_output_items": native_output_items,
            "tool_outputs": stored_tool_outputs,
            "retention": "ephemeral" if ephemeral else "session",
            "created_at": time.time(),
        }
        _RESPONSE_STATE_ORDER.append(response_id)
        while len(_RESPONSE_STATE_ORDER) > MAX_RESPONSE_STATE:
            stale = _RESPONSE_STATE_ORDER.popleft()
            _RESPONSE_STATE.pop(stale, None)


@dataclass(frozen=True)
class ResponseHistory:
    messages: list[dict[str, Any]]
    function_calls: dict[str, str]
    function_call_items: dict[str, dict[str, Any]]
    tool_outputs: set[tuple[str, str]]
    replayed: bool


def _function_call_arguments(item: Mapping[str, Any]) -> str:
    arguments = item.get("arguments", "")
    if isinstance(arguments, str):
        return arguments
    if isinstance(arguments, (Mapping, list)):
        return _json_dumps(arguments)
    if arguments is None:
        return ""
    raise FacadeError(
        "Responses function_call arguments must be a JSON string",
        status_code=400,
        code="invalid_function_call_arguments",
        param="input",
    )


def _function_call_metadata(item: Mapping[str, Any]) -> tuple[str, str]:
    return _clean(item.get("call_id")), _clean(item.get("name"))


def _function_call_item(
    item: Mapping[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    call_id, name = _function_call_metadata(item)
    if not call_id or not name:
        if strict:
            raise FacadeError(
                "Responses function_call items require call_id and name",
                status_code=400,
                code="invalid_function_call",
                param="input",
            )
        return {}
    function_call = {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": _function_call_arguments(item),
    }
    for field in ("id", "status"):
        value = item.get(field)
        if isinstance(value, str) and value:
            function_call[field] = value
    return function_call


def _function_call_context_message(item: Mapping[str, Any]) -> dict[str, Any]:
    function_call = _function_call_item(item)
    if not function_call:
        raise ValueError("Function call context requires call_id and name")
    return {
        "role": "assistant",
        "content": _json_dumps(function_call),
        **function_call,
    }


def _function_call_output_context_message(
    *,
    call_id: str,
    output: str,
) -> dict[str, Any]:
    function_call_output = {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
    }
    return {
        "role": "tool",
        "content": _json_dumps(function_call_output),
        **function_call_output,
    }


def _function_calls_from_items(items: list[dict[str, Any]]) -> dict[str, str]:
    calls: dict[str, str] = {}
    for item in items:
        if _clean(item.get("type")) != "function_call":
            continue
        call_id, name = _function_call_metadata(item)
        if call_id and name:
            calls[call_id] = name
    return calls


def _function_call_items_from_items(
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    for item in items:
        if _clean(item.get("type")) != "function_call":
            continue
        function_call = _function_call_item(item)
        if function_call:
            calls[function_call["call_id"]] = function_call
    return calls


def _function_calls_from_state(state: Mapping[str, Any]) -> dict[str, str]:
    calls = _function_calls_from_items(_messages(state.get("function_calls")))
    # States created before call metadata was compacted retained full output items.
    calls.update(_function_calls_from_items(_messages(state.get("output_items"))))
    calls.update(
        _function_calls_from_items(_messages(state.get("native_response_output_items")))
    )
    calls.update(_function_calls_from_items(_messages(state.get("messages"))))
    return calls


def _function_call_items_from_state(
    state: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    calls = _function_call_items_from_items(_messages(state.get("function_calls")))
    calls.update(_function_call_items_from_items(_messages(state.get("output_items"))))
    calls.update(
        _function_call_items_from_items(
            _messages(state.get("native_response_output_items"))
        )
    )
    calls.update(_function_call_items_from_items(_messages(state.get("messages"))))
    return calls


def _legacy_replayed_function_call(message: Mapping[str, Any]) -> tuple[str, str]:
    if _clean(message.get("role")) != "assistant":
        return "", ""
    content = _clean(message.get("content"))
    if not content.startswith(LEGACY_REPLAYED_FUNCTION_CALL_PREFIX):
        return "", ""
    try:
        call = json.loads(content.removeprefix(LEGACY_REPLAYED_FUNCTION_CALL_PREFIX))
    except (TypeError, ValueError):
        return "", ""
    if not isinstance(call, Mapping):
        return "", ""
    return _function_call_metadata(call)


def _tool_output_metadata(item: Mapping[str, Any]) -> tuple[str, str]:
    """Return a valid tool result without altering its output bytes."""

    output = item.get("output")
    if not isinstance(output, str):
        raise FacadeError(
            "Responses function_call_output output must be a string",
            status_code=400,
            code="invalid_function_call_output",
            param="input",
        )
    return _clean(item.get("call_id")), output


def _tool_outputs_from_state(state: Mapping[str, Any]) -> set[tuple[str, str]]:
    outputs: set[tuple[str, str]] = set()
    for item in _messages(state.get("tool_outputs")):
        outputs.add(_tool_output_metadata(item))
    return outputs


def _legacy_tool_output_metadata(message: Mapping[str, Any]) -> tuple[str, str]:
    if _clean(message.get("role")) != "tool":
        return "", ""
    content = _clean(message.get("content"))
    prefix = "Tool output for "
    if not content.startswith(prefix):
        return "", ""
    call_id, separator, output = content.removeprefix(prefix).partition(": ")
    if not separator:
        return "", ""
    return _clean(call_id), output


def _message_context_chars(message: Mapping[str, Any]) -> int:
    """Measure only the prompt content the local text adapter receives."""

    content = message.get("content", "")
    if isinstance(content, str):
        return len(content)
    return len(_json_dumps(content))


def _compact_replayed_text(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= len(REPLAYED_CONTEXT_OMITTED):
        return REPLAYED_CONTEXT_OMITTED[:limit]
    retained = limit - len(REPLAYED_CONTEXT_OMITTED)
    prefix_chars = retained // 2
    suffix_chars = retained - prefix_chars
    return text[:prefix_chars] + REPLAYED_CONTEXT_OMITTED + text[-suffix_chars:]


def _compact_replayed_message(
    message: Mapping[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    compacted = dict(message)
    content = compacted.get("content", "")
    if not isinstance(content, str):
        content = _json_dumps(content)
    compacted["content"] = _compact_replayed_text(content, limit=limit)
    return compacted


def _compact_replayed_tool_output(
    message: Mapping[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    call_id = _clean(message.get("call_id"))
    output = message.get("output")
    if not call_id or not isinstance(output, str):
        return _compact_replayed_message(message, limit=limit)
    if limit <= 0:
        return _function_call_output_context_message(
            call_id=call_id,
            output=REPLAYED_TOOL_OUTPUT_OMITTED,
        )
    return _function_call_output_context_message(
        call_id=call_id,
        output=_compact_replayed_text(output, limit=limit),
    )


def _compact_replayed_history(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bound prompt-only replay without changing authoritative call state.

    Function-call metadata and exact tool outputs are retained separately in
    response state for continuation validation. This function only constrains
    the text copy sent back through the local text adapter on a later turn.
    """

    replayed = [
        dict(message) for message in messages if not _is_tool_contract_message(message)
    ]
    replayed_chars = sum(_message_context_chars(message) for message in replayed)
    if replayed_chars <= MAX_REPLAYED_HISTORY_CHARS:
        return replayed

    tool_output_indexes = [
        index
        for index, message in enumerate(replayed)
        if _clean(message.get("type")) == "function_call_output"
    ]
    retained_tool_outputs = set(tool_output_indexes[-MAX_REPLAYED_TOOL_OUTPUTS:])
    for index in tool_output_indexes:
        output_limit = (
            MAX_REPLAYED_TOOL_OUTPUT_CHARS if index in retained_tool_outputs else 0
        )
        replayed[index] = _compact_replayed_tool_output(
            replayed[index],
            limit=output_limit,
        )

    replayed_chars = sum(_message_context_chars(message) for message in replayed)
    if replayed_chars <= MAX_REPLAYED_HISTORY_CHARS:
        return replayed

    # Retain the opening instructions/task plus the newest conversation
    # context. Historical tool contracts are always regenerated below from the
    # current request, so they never consume the replay budget.
    anchor_indexes: list[int] = []
    for index, message in enumerate(replayed):
        if _is_tool_contract_message(message):
            continue
        if _clean(message.get("role")) not in {"system", "user"}:
            continue
        anchor_indexes.append(index)
        if len(anchor_indexes) == 3:
            break

    compacted: dict[int, dict[str, Any]] = {}
    remaining = MAX_REPLAYED_HISTORY_CHARS
    for index in anchor_indexes:
        message = _compact_replayed_message(
            replayed[index],
            limit=min(MAX_REPLAYED_HISTORY_ANCHOR_CHARS, remaining),
        )
        compacted[index] = message
        remaining -= _message_context_chars(message)

    for index in range(len(replayed) - 1, -1, -1):
        if index in compacted or _is_tool_contract_message(replayed[index]):
            continue
        message = replayed[index]
        message_chars = _message_context_chars(message)
        if message_chars <= remaining:
            compacted[index] = message
            remaining -= message_chars
            continue
        if remaining <= len(REPLAYED_CONTEXT_OMITTED):
            continue
        compacted[index] = _compact_replayed_message(
            message,
            limit=remaining,
        )
        break

    return [compacted[index] for index in sorted(compacted)]


def _previous_response_history(
    previous_response_id: str,
    *,
    compact: bool = True,
) -> ResponseHistory:
    previous_response_id = _clean(previous_response_id)
    if not previous_response_id:
        return ResponseHistory([], {}, {}, set(), False)
    with _RESPONSE_STATE_LOCK:
        state = dict(_RESPONSE_STATE.get(previous_response_id) or {})
    if not state:
        return ResponseHistory([], {}, {}, set(), False)
    function_calls = _function_calls_from_state(state)
    function_call_items = _function_call_items_from_state(state)
    tool_outputs = _tool_outputs_from_state(state)
    messages: list[dict[str, Any]] = []
    for message in _messages(state.get("messages")):
        call_id, name = _legacy_replayed_function_call(message)
        if call_id and name:
            function_calls[call_id] = name
            function_call_items.setdefault(
                call_id,
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": "",
                },
            )
            continue
        messages.append(message)
        legacy_tool_output = _legacy_tool_output_metadata(message)
        if legacy_tool_output != ("", ""):
            tool_outputs.add(legacy_tool_output)
    output_text = _clean(state.get("output_text"))
    if output_text and not _flag(state.get("messages_include_response_output")):
        messages.append({"role": "assistant", "content": output_text})
    native_response_output_items = _messages(state.get("native_response_output_items"))
    if native_response_output_items:
        messages.extend(native_response_output_items)
    else:
        existing_call_ids = {
            _clean(message.get("call_id"))
            for message in messages
            if _clean(message.get("type")) == "function_call"
        }
        for call_id, function_call in function_call_items.items():
            if call_id not in existing_call_ids:
                messages.append(_function_call_context_message(function_call))
    return ResponseHistory(
        _compact_replayed_history(messages) if compact else messages,
        function_calls,
        function_call_items,
        tool_outputs,
        True,
    )


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
    message = _choice_message(payload)
    content = message.get("content")
    return content if isinstance(content, str) else _clean(content)


def _choice_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices:
        return {}
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message")
    return dict(message) if isinstance(message, Mapping) else {}


def _norman_options(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("norman")
    return dict(value) if isinstance(value, Mapping) else {}


def _tools(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tools")
    return [dict(item) for item in value] if isinstance(value, list) else []


def _tool_name(tool: Mapping[str, Any]) -> str:
    function = _mapping(tool.get("function"))
    return _clean(function.get("name") or tool.get("name"))


def _namespace_member_name(namespace: str, member: Mapping[str, Any]) -> str:
    member_type = _clean(member.get("type"))
    if member_type and member_type != "function":
        return ""
    member_name = _tool_name(member)
    if not member_name:
        return ""
    if member_name.startswith(f"{namespace}."):
        return member_name
    return f"{namespace}.{member_name}"


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if _clean(tool.get("type")) != "namespace":
            name = _tool_name(tool)
            if name:
                names.add(name)
            continue

        namespace = _clean(tool.get("name"))
        members = tool.get("tools")
        if not namespace or not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, Mapping):
                continue
            member_name = _namespace_member_name(namespace, member)
            if member_name:
                names.add(member_name)
    return names


@dataclass(frozen=True)
class ToolChainContext:
    chain_depth: int
    tool_results_supplied: int
    tool_results_matched: int
    successful_tool_results: int
    successful_call_signatures: frozenset[tuple[str, str]]


def _tool_chain_context(
    payload: Mapping[str, Any],
    *,
    function_call_items: Mapping[str, Mapping[str, Any]],
    known_tool_outputs: set[tuple[str, str]],
) -> ToolChainContext:
    calls: dict[str, dict[str, Any]] = {}
    for call_id, function_call in function_call_items.items():
        normalized_call = _function_call_item(function_call)
        if call_id and normalized_call:
            calls[call_id] = normalized_call
    raw_input = payload.get("input", payload.get("prompt"))
    supplied_results = set(known_tool_outputs)
    if isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, Mapping):
                continue
            item_type = _clean(item.get("type"))
            if item_type == "function_call":
                function_call = _function_call_item(item)
                if function_call:
                    calls[function_call["call_id"]] = function_call
            elif item_type == "function_call_output":
                tool_output = _tool_output_metadata(item)
                supplied_results.add(tool_output)
    matched_result_names = [
        calls[call_id]["name"]
        for call_id, _ in supplied_results
        if call_id and call_id in calls
    ]
    successful_tool_results = sum(
        1
        for call_id, output in supplied_results
        if call_id in calls and _tool_output_is_successful(output)
    )
    successful_call_signatures = frozenset(
        _function_call_signature(calls[call_id])
        for call_id, output in supplied_results
        if call_id in calls and _tool_output_is_successful(output)
    )
    return ToolChainContext(
        chain_depth=len(calls),
        tool_results_supplied=len(supplied_results),
        tool_results_matched=len(matched_result_names),
        successful_tool_results=successful_tool_results,
        successful_call_signatures=successful_call_signatures,
    )


def _trailing_json_tool_call_envelope(
    text: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Split a JSON tool envelope from adjacent assistant prose.

    Some local models announce an action before emitting the tool JSON. The
    envelope is meaningful when it is a complete, standalone final object or
    the first meaningful object in the response. The latter shape occurs when
    a provider emits the tool call and a short status sentence in one turn.
    Ordinary JSON answers remain assistant text.
    """

    if not text:
        return "", []
    fenced_envelope = _trailing_fenced_json_tool_call_envelope(text)
    if fenced_envelope is not None:
        preamble, fenced_json = fenced_envelope
        try:
            payload = json.loads(fenced_json)
        except (TypeError, ValueError):
            payload = None
        calls = _tool_calls_from_envelope_payload(payload)
        if calls:
            return preamble, calls
    decoder = json.JSONDecoder()
    start = text.rfind("{")
    while start >= 0:
        if start and not text[start - 1].isspace():
            start = text.rfind("{", 0, start)
            continue
        try:
            payload, end = decoder.raw_decode(text[start:])
        except (TypeError, ValueError):
            start = text.rfind("{", 0, start)
            continue
        if text[start + end :].strip():
            start = text.rfind("{", 0, start)
            continue
        calls = _tool_calls_from_envelope_payload(payload)
        if calls:
            preamble = text[:start]
            return (preamble if preamble.strip() else ""), calls
        start = text.rfind("{", 0, start)
    leading_envelope = _leading_json_tool_call_envelope(text)
    if leading_envelope is not None:
        return leading_envelope
    return text, []


def _trailing_fenced_json_tool_call_envelope(text: str) -> tuple[str, str] | None:
    """Return the prose and JSON from a final generic or JSON fenced block."""

    match = re.fullmatch(
        r"(?s)(.*)```(?i:json)?[ \t]*\r?\n(.*?)\r?\n?```[ \t]*",
        text,
    )
    if match is None:
        return None
    return match.group(1), match.group(2)


def _leading_json_tool_call_envelope(
    text: str,
) -> tuple[str, list[dict[str, Any]]] | None:
    """Return prose following a complete initial JSON tool-call envelope."""

    leading_characters = len(text) - len(text.lstrip())
    candidate = text[leading_characters:]
    if not candidate.startswith("{"):
        return None
    try:
        payload, end = json.JSONDecoder().raw_decode(candidate)
    except (TypeError, ValueError):
        return None
    calls = _tool_calls_from_envelope_payload(payload)
    if not calls:
        return None
    trailing_text = candidate[end:]
    return (trailing_text if trailing_text.strip() else ""), calls


def _tool_calls_from_envelope_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    raw_calls: list[Any] = []
    if isinstance(payload.get("tool_call"), Mapping):
        raw_calls = [payload["tool_call"]]
    elif isinstance(payload.get("tool_calls"), list):
        raw_calls = payload["tool_calls"]
    elif _clean(payload.get("type")) == "function_call" and _clean(payload.get("name")):
        # Some local model adapters return a native Responses output item
        # directly instead of wrapping it in a local ``tool_call`` envelope.
        raw_calls = [payload]
    return [dict(call) for call in raw_calls if isinstance(call, Mapping)]


def _json_tool_call_envelope(text: str) -> list[dict[str, Any]]:
    _, calls = _trailing_json_tool_call_envelope(text)
    return calls


def _tool_output_is_successful(output: str) -> bool:
    """Classify a supplied result for passive Responses telemetry."""

    normalized = _lower(output)
    if not normalized:
        return False
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, Mapping):
        error = parsed.get("error")
        if error not in (None, "", {}, []):
            return False
        for field in ("status", "status_code", "statusCode"):
            value = parsed.get(field)
            if isinstance(value, int) and value >= 400:
                return False
    return not any(marker in normalized for marker in TOOL_OUTPUT_FAILURE_MARKERS)


def _canonical_function_call_arguments(arguments: Any) -> str:
    raw_arguments = arguments if isinstance(arguments, str) else _json_dumps(arguments)
    try:
        return _json_dumps(json.loads(raw_arguments))
    except (TypeError, ValueError):
        return _clean(raw_arguments)


def _function_call_signature(item: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _clean(item.get("name")),
        _canonical_function_call_arguments(item.get("arguments")),
    )


def _function_call_contract_matches(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    """Compare the executable portion of a Responses function-call item.

    Codex may replay a completed function call alongside its output while
    changing transport metadata such as the output item ``id`` or ``status``.
    Those fields do not affect which tool is invoked, so they must not make a
    valid continuation look conflicting.
    """

    return _clean(left.get("call_id")) == _clean(
        right.get("call_id")
    ) and _function_call_signature(left) == _function_call_signature(right)


def _function_call_is_in_progress(item: Mapping[str, Any]) -> bool:
    return _lower(item.get("status")) == "in_progress"


def _function_call_arguments_extend(
    partial: Mapping[str, Any],
    complete: Mapping[str, Any],
) -> bool:
    """Return whether an in-progress argument snapshot can become ``complete``."""

    partial_arguments = _canonical_function_call_arguments(partial.get("arguments"))
    complete_arguments = _canonical_function_call_arguments(complete.get("arguments"))
    return not partial_arguments or complete_arguments.startswith(partial_arguments)


def _prefer_function_call_snapshot(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the more complete replay snapshot while retaining its metadata."""

    left_arguments = _canonical_function_call_arguments(left.get("arguments"))
    right_arguments = _canonical_function_call_arguments(right.get("arguments"))
    if _function_call_is_in_progress(left) != _function_call_is_in_progress(right):
        return dict(right if _function_call_is_in_progress(left) else left)
    if len(right_arguments) >= len(left_arguments):
        return dict(right)
    return dict(left)


def _reconcile_function_call_replay(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Coalesce compatible Codex lifecycle snapshots of one function call.

    A streamed ``response.output_item.added`` event carries an in-progress call
    with empty or partial arguments, then the completed output item carries the
    final arguments. Codex can replay both representations in a follow-up
    Responses request. They must collapse to the completed call, while a
    changed name or non-monotonic argument value remains a caller error.
    """

    if _clean(left.get("call_id")) != _clean(right.get("call_id")):
        return None
    if _clean(left.get("name")) != _clean(right.get("name")):
        return None
    if _function_call_contract_matches(left, right):
        return _prefer_function_call_snapshot(left, right)
    if _function_call_is_in_progress(left) and _function_call_arguments_extend(
        left, right
    ):
        return _prefer_function_call_snapshot(left, right)
    if _function_call_is_in_progress(right) and _function_call_arguments_extend(
        right, left
    ):
        return _prefer_function_call_snapshot(left, right)
    return None


def _tool_chain_telemetry(
    *,
    context: ToolChainContext,
    tool_calls: list[dict[str, Any]],
    outcome: str = "",
    watchdog_state: str = "normal",
    watchdog_attempts: int = 0,
) -> dict[str, Any]:
    if not outcome:
        if tool_calls:
            outcome = "tool_call"
        elif context.tool_results_supplied:
            outcome = "final_after_tool"
        else:
            outcome = "final_without_tool"
    return {
        "schema": TOOL_CHAIN_SCHEMA,
        "turn_type": (
            "after_tool_result" if context.tool_results_supplied else "initial_or_text"
        ),
        "chain_depth": context.chain_depth,
        "tool_results_supplied": context.tool_results_supplied,
        "tool_results_matched": context.tool_results_matched,
        "successful_tool_results": context.successful_tool_results,
        "tool_calls_returned": len(tool_calls),
        "outcome": outcome,
        "watchdog": {
            "state": watchdog_state,
            "attempts": max(0, watchdog_attempts),
        },
    }


def _tool_contract_definition(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    tools = _tools(payload)
    compact = []
    for tool in tools:
        if _clean(tool.get("type")) == "namespace":
            namespace = _clean(tool.get("name"))
            members = tool.get("tools")
            if not namespace or not isinstance(members, list):
                continue
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                name = _namespace_member_name(namespace, member)
                if not name:
                    continue
                function = _mapping(member.get("function"))
                compact.append(
                    {
                        "name": name,
                        "type": "function",
                        "description": _clean(
                            function.get("description") or member.get("description")
                        ),
                        "parameters": function.get("parameters")
                        or member.get("parameters")
                        or {},
                    }
                )
            continue

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
    return compact


def _tool_contract_message(
    payload: Mapping[str, Any],
    *,
    bridge_mode: str = TRANSPARENT_BRIDGE_MODE,
) -> list[dict[str, Any]]:
    compact = _tool_contract_definition(payload)
    if not compact:
        return []
    if bridge_mode == GOVERNED_BRIDGE_MODE:
        content = (
            "When calling tools, return only one JSON object using either "
            '{"tool_call":{"name":"tool_name","arguments":{}}} or '
            '{"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
            "Use only a tool name declared below. After a tool result, "
            "continue with another tool only when the result establishes "
            "that additional work is needed; otherwise return the final "
            "assistant answer. Do not repeat a completed call merely "
            "because it remains available. Available tools: "
        )
    else:
        content = (
            "This local text adapter encodes function calls as JSON. When a "
            "function is needed, emit exactly one JSON object using either "
            '{"tool_call":{"name":"tool_name","arguments":{}}} or '
            '{"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
            "Use only a declared tool name. Available tools: "
        )
    return [
        {
            "role": "system",
            "content": content + _json_dumps(compact),
            TOOL_CONTRACT_CONTEXT_MARKER: {
                "kind": TOOL_CONTRACT_CONTEXT_KIND,
                "tools": compact,
                "bridge_mode": bridge_mode,
            },
        }
    ]


def _is_tool_contract_message(message: Mapping[str, Any]) -> bool:
    marker = _mapping(message.get(TOOL_CONTRACT_CONTEXT_MARKER))
    return _clean(marker.get("kind")) == TOOL_CONTRACT_CONTEXT_KIND


def _message_has_tool_contract(
    message: Mapping[str, Any],
    *,
    definition: list[dict[str, Any]],
    bridge_mode: str = TRANSPARENT_BRIDGE_MODE,
) -> bool:
    marker = _mapping(message.get(TOOL_CONTRACT_CONTEXT_MARKER))
    if _clean(marker.get("kind")) != TOOL_CONTRACT_CONTEXT_KIND:
        return False
    return (
        _messages(marker.get("tools")) == definition
        and _clean(marker.get("bridge_mode")) == bridge_mode
    )


def _messages_with_current_tool_contract(
    messages: list[dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    bridge_mode: str = TRANSPARENT_BRIDGE_MODE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Replay ordinary history and send exactly one current tool registry.

    The local text adapter cannot consume native structured tool definitions,
    so each registry is rendered as a system message. Old rendered registries
    are prompt-only compatibility data, not authoritative call state; keeping
    them makes every continuation resend an expanding catalog. Exact call
    metadata remains in server-side response state for validation.
    """

    definition = _tool_contract_definition(payload)
    history = [
        dict(message) for message in messages if not _is_tool_contract_message(message)
    ]
    if not definition:
        return history, []
    return history, _tool_contract_message(payload, bridge_mode=bridge_mode)


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


def _uses_native_mantle_responses(payload: Mapping[str, Any]) -> bool:
    """Keep the Terra route on its native Bedrock Responses protocol."""

    return _requested_model(payload).lower() in {
        "gpt-5.6-terra",
        "openai.gpt-5.6-terra",
    }


def _responses_bridge_mode(payload: Mapping[str, Any]) -> str:
    """Select the explicit tool-bridge behavior for a Responses request."""

    if _requested_model(payload).lower() in GOVERNED_BRIDGE_MODEL_ALIASES:
        return GOVERNED_BRIDGE_MODE
    return TRANSPARENT_BRIDGE_MODE


def _facade_max_tokens(payload: Mapping[str, Any]) -> int:
    return _positive_int(
        payload.get("max_completion_tokens")
        or payload.get("max_output_tokens")
        or payload.get("max_tokens"),
        DEFAULT_FACADE_TOKENS,
    )


def _requested_output_token_budget(payload: Mapping[str, Any]) -> int | None:
    for key in ("max_completion_tokens", "max_output_tokens", "max_tokens"):
        if key not in payload:
            continue
        try:
            requested = int(payload.get(key) or 0)
        except (TypeError, ValueError):
            return None
        return requested if requested > 0 else None
    return None


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


def _validate_supported_responses_fields(payload: Mapping[str, Any]) -> None:
    """Reject only Responses semantics the local facade cannot safely emulate.

    Responses evolves independently of this facade. Unknown request fields are
    intentionally opaque: they remain available to route policy and must not
    turn a newer Codex client into a preflight failure.
    """

    for key in payload:
        if key not in UNSUPPORTED_RESPONSES_SEMANTIC_FIELDS:
            continue
        raise FacadeError(
            f"Unsupported OpenAI-compatible facade parameter: {key}",
            status_code=501,
            error_type="unsupported_parameter",
            code="unsupported_parameter",
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
    advisory: dict[str, str] = {}
    known_values = {
        "effort": SUPPORTED_REASONING_EFFORTS,
        "summary": SUPPORTED_REASONING_SUMMARIES,
        "context": SUPPORTED_REASONING_CONTEXTS,
    }
    for key, supported_values in known_values.items():
        value = reasoning.get(key)
        normalized = _lower(value) if isinstance(value, str) else ""
        if normalized in supported_values:
            advisory[key] = normalized
    return advisory


def _responses_include_advisory(payload: Mapping[str, Any]) -> list[str]:
    """Return opaque Responses include metadata without constraining its values."""

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
    return list(include)


def _native_mantle_responses_options(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep native Responses options structured for the Terra Mantle route."""

    options: dict[str, Any] = {}
    tools = _tools(payload)
    if tools:
        options["tools"] = tools
    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, (str, Mapping)):
        options["tool_choice"] = (
            dict(tool_choice) if isinstance(tool_choice, Mapping) else tool_choice
        )
    if isinstance(payload.get("parallel_tool_calls"), bool):
        options["parallel_tool_calls"] = payload["parallel_tool_calls"]
    reasoning = _responses_reasoning_advisory(payload)
    if reasoning:
        options["reasoning"] = reasoning
    text = _mapping(payload.get("text"))
    if text:
        options["text"] = text
    include = _responses_include_advisory(payload)
    if include:
        options["include"] = include
    return options


def _native_mantle_function_call_items(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract native Responses function calls without parsing assistant text."""

    output = raw.get("output")
    if not isinstance(output, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        if _clean(item.get("type")) != "function_call":
            continue
        function_call = _function_call_item(item)
        if function_call:
            calls.append(function_call)
    return calls


def _native_mantle_response_output_items(
    raw: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Keep native Terra output items for a reasoning/tool continuation."""

    output = raw.get("output")
    if not isinstance(output, list):
        return []
    return [
        dict(item)
        for item in output
        if isinstance(item, Mapping)
        and _clean(item.get("type")) in {"reasoning", "function_call", "message"}
    ]


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
        text = part.get("text")
        return text if isinstance(text, str) else _clean(text)
    if part_type in {"output_text"}:
        text = part.get("text")
        return text if isinstance(text, str) else _clean(text)
    raise FacadeError(
        f"Unsupported Responses input content item type: {part_type or '<blank>'}",
        status_code=501,
        error_type="unsupported_parameter",
        code="unsupported_input_content",
        param="input",
    )


def _response_input_function_call_items(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_input = payload.get("input", payload.get("prompt"))
    if not isinstance(raw_input, list):
        return {}
    function_calls: dict[str, dict[str, Any]] = {}
    for item in _messages(raw_input):
        if _clean(item.get("type")) != "function_call":
            continue
        function_call = _function_call_item(item, strict=True)
        previous = function_calls.get(function_call["call_id"])
        reconciled = (
            _reconcile_function_call_replay(previous, function_call)
            if previous
            else function_call
        )
        if not reconciled:
            raise FacadeError(
                "Responses input contains conflicting function_call items",
                status_code=400,
                code="function_call_mismatch",
                param="input",
            )
        function_calls[function_call["call_id"]] = reconciled
    return function_calls


def _response_input_tool_outputs(
    payload: Mapping[str, Any],
) -> set[tuple[str, str]]:
    raw_input = payload.get("input", payload.get("prompt"))
    if not isinstance(raw_input, list):
        return set()
    outputs: set[tuple[str, str]] = set()
    for item in _messages(raw_input):
        if _clean(item.get("type")) == "function_call_output":
            outputs.add(_tool_output_metadata(item))
    return outputs


def _validate_response_tool_continuation(
    payload: Mapping[str, Any],
    *,
    known_function_call_items: Mapping[str, Mapping[str, Any]],
    known_tool_outputs: set[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Validate caller-supplied call/output linkage without repairing it."""

    function_call_items = {
        call_id: dict(item)
        for call_id, item in known_function_call_items.items()
        if call_id
    }
    for call_id, function_call in _response_input_function_call_items(payload).items():
        known = function_call_items.get(call_id)
        reconciled = (
            _reconcile_function_call_replay(known, function_call)
            if known
            else function_call
        )
        if not reconciled:
            raise FacadeError(
                "Responses function_call does not match its prior call_id",
                status_code=400,
                code="function_call_mismatch",
                param="input",
            )
        function_call_items[call_id] = reconciled

    raw_input = payload.get("input", payload.get("prompt"))
    if not isinstance(raw_input, list):
        return function_call_items
    seen_outputs: dict[str, str] = {}
    for call_id, output in known_tool_outputs:
        previous_output = seen_outputs.get(call_id)
        if previous_output is not None and previous_output != output:
            raise FacadeError(
                "Responses history contains conflicting function_call_output items",
                status_code=400,
                code="function_call_output_mismatch",
                param="previous_response_id",
            )
        seen_outputs[call_id] = output
    for item in _messages(raw_input):
        if _clean(item.get("type")) != "function_call_output":
            continue
        call_id, output = _tool_output_metadata(item)
        if not call_id or call_id not in function_call_items:
            raise FacadeError(
                "Responses function_call_output must reference a known call_id",
                status_code=400,
                code="unknown_function_call_id",
                param="input",
            )
        previous_output = seen_outputs.get(call_id)
        if previous_output is not None and previous_output != output:
            raise FacadeError(
                "Responses input contains conflicting function_call_output items",
                status_code=400,
                code="function_call_output_mismatch",
                param="input",
            )
        seen_outputs[call_id] = output
    return function_call_items


def response_input_to_messages(
    payload: Mapping[str, Any],
    *,
    known_tool_outputs: set[tuple[str, str]] | None = None,
    known_function_call_items: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    seen_tool_outputs = set(known_tool_outputs or ())
    function_call_items = {
        call_id: dict(item)
        for call_id, item in dict(known_function_call_items or {}).items()
        if call_id
    }
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
                function_call = _function_call_item(item, strict=True)
                existing = function_call_items.get(function_call["call_id"])
                if existing:
                    reconciled = _reconcile_function_call_replay(
                        existing, function_call
                    )
                    if not reconciled:
                        raise FacadeError(
                            "Responses function_call does not match its prior call_id",
                            status_code=400,
                            code="function_call_mismatch",
                            param="input",
                        )
                    function_call_items[function_call["call_id"]] = reconciled
                    # Codex may resend a prior call item with its output. The
                    # stored conversation already contains it in order.
                    continue
                function_call_items[function_call["call_id"]] = function_call
                messages.append(_function_call_context_message(function_call))
                continue
            if item_type == "function_call_output":
                call_id, output = _tool_output_metadata(item)
                if not call_id or call_id not in function_call_items:
                    raise FacadeError(
                        "Responses function_call_output must reference a known call_id",
                        status_code=400,
                        code="unknown_function_call_id",
                        param="input",
                    )
                tool_output = (call_id, output)
                if tool_output in seen_tool_outputs:
                    continue
                seen_tool_outputs.add(tool_output)
                messages.append(
                    _function_call_output_context_message(
                        call_id=call_id,
                        output=output,
                    )
                )
                continue
            if item_type not in {"", "message"}:
                # Generated Responses items such as reasoning are opaque to
                # this text-only local lane. They are not user messages and
                # must not turn an otherwise valid tool continuation into a
                # compatibility error.
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
    allow_implicit_tools: bool = False,
    raw_calls: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    names = _tool_names(tools)
    if not text or (not names and not allow_implicit_tools):
        return []
    if raw_calls is None:
        raw_calls = _json_tool_call_envelope(text)
    calls: list[dict[str, Any]] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        name = _clean(raw.get("name"))
        if not name:
            continue
        arguments = raw.get("arguments", {})
        if name not in names and not allow_implicit_tools:
            continue
        call_id = _clean(raw.get("call_id")) or f"call_{uuid.uuid4().hex}"
        calls.append(
            {
                "id": _clean(raw.get("id")) or f"fc_{uuid.uuid4().hex}",
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


def _response_tool_calls(
    text: str,
    *,
    provider_payload: Mapping[str, Any],
    normalized_output: NormalizedResponsesOutput | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    tools = _tools(provider_payload)
    if normalized_output is not None and normalized_output.raw_text == text:
        preamble = normalized_output.visible_text
        raw_calls = [dict(call) for call in normalized_output.raw_tool_calls]
    else:
        preamble, raw_calls = _trailing_json_tool_call_envelope(text)
    tool_calls = _extract_tool_calls(
        text,
        tools=tools,
        # Some Codex TUI request forms keep their executable tool registry
        # client-side and omit a top-level Responses tools list. The TUI still
        # validates the returned call before it can execute anything.
        allow_implicit_tools="tools" not in provider_payload,
        raw_calls=raw_calls,
    )
    # The stream normalizer intentionally does not know the caller's tool
    # registry. If a tool-shaped JSON object names an undeclared tool, preserve
    # it as regular assistant text instead of silently dropping the envelope.
    if raw_calls and not tool_calls:
        return text, []
    return preamble, tool_calls


def _repeats_successful_tool_call(
    text: str,
    *,
    prepared: PreparedResponsesExecution,
    normalized_output: NormalizedResponsesOutput | None = None,
) -> bool:
    if not prepared.tool_chain_context.successful_call_signatures:
        return False
    _, tool_calls = _response_tool_calls(
        text,
        provider_payload=prepared.provider_payload,
        normalized_output=normalized_output,
    )
    return any(
        _function_call_signature(tool_call)
        in prepared.tool_chain_context.successful_call_signatures
        for tool_call in tool_calls
    )


_TOOL_CONTINUATION_REPAIR_MESSAGE = (
    "A prior tool result is authoritative. Do not repeat an equivalent completed "
    "function call. Return the final answer, or issue only a materially different "
    "function call that is still necessary."
)


def _tool_continuation_repair_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        *messages,
        {"role": "system", "content": _TOOL_CONTINUATION_REPAIR_MESSAGE},
    ]


def _tool_continuation_exhausted_error(
    prepared: PreparedResponsesExecution,
) -> FacadeError:
    return FacadeError(
        "Tool continuation remained invalid after the bounded Norman repair.",
        status_code=502,
        error_type="server_error",
        code="tool_continuation_exhausted",
        norman={
            "responses_compatibility": {
                "tool_chain": _tool_chain_telemetry(
                    context=prepared.tool_chain_context,
                    tool_calls=[],
                    outcome="invalid_or_unresolved",
                    watchdog_state="exhausted",
                    watchdog_attempts=1,
                )
            }
        },
    )


@dataclass(frozen=True)
class NormalizedResponsesOutput:
    """Canonical Responses output derived from one model text stream."""

    raw_text: str
    visible_text: str
    raw_tool_calls: list[dict[str, Any]]


class ResponsesStreamNormalizer:
    """Keep local text tool envelopes out of Responses text events.

    Local providers do not expose native Responses function-call events. This
    adapter recognizes final, standalone local ``tool_call``/``tool_calls``
    envelopes and native ``function_call`` output items. It buffers a possible
    call across arbitrary upstream fragment boundaries so the streamed text
    and completed response can be built from the same result.
    """

    _MAX_PENDING_PREFIX_CHARS = 256
    _MAX_PENDING_NATIVE_FUNCTION_CALL_CHARS = 1_048_576
    _TOOL_ENVELOPE_KEYS = frozenset({"tool_call", "tool_calls"})
    _NATIVE_FUNCTION_CALL_KEYS = frozenset(
        {"arguments", "call_id", "id", "name", "status", "type"}
    )

    def __init__(self) -> None:
        self._raw_parts: list[str] = []
        self._pending = ""
        self._emitted_parts: list[str] = []
        self._finalized: NormalizedResponsesOutput | None = None

    @property
    def raw_text(self) -> str:
        return "".join(self._raw_parts)

    @property
    def emitted_text(self) -> str:
        return "".join(self._emitted_parts)

    def feed(self, fragment: str) -> list[str]:
        """Return assistant-text deltas that are safe to send immediately."""

        if self._finalized is not None:
            raise RuntimeError("Responses stream normalizer is already finalized")
        if not fragment:
            return []
        self._raw_parts.append(fragment)
        self._pending += fragment
        return self._drain_pending()

    def finalize(self) -> NormalizedResponsesOutput:
        """Freeze the canonical text/tool split after the upstream completes."""

        if self._finalized is not None:
            return self._finalized
        visible_text, raw_tool_calls = _trailing_json_tool_call_envelope(self.raw_text)
        emitted_text = self.emitted_text
        if raw_tool_calls and not visible_text.startswith(emitted_text):
            # A malformed or non-trailing candidate may have already been
            # streamed as text. Preserve that text instead of retracting it.
            visible_text = self.raw_text
            raw_tool_calls = []
        self._finalized = NormalizedResponsesOutput(
            raw_text=self.raw_text,
            visible_text=visible_text if raw_tool_calls else self.raw_text,
            raw_tool_calls=[dict(call) for call in raw_tool_calls],
        )
        return self._finalized

    def _drain_pending(self) -> list[str]:
        deltas: list[str] = []
        while self._pending:
            candidate_start = self._candidate_start(self._pending)
            if candidate_start < 0:
                if not self._emitted_parts and not self._pending.strip():
                    break
                deltas.append(self._emit_pending())
                break
            if candidate_start:
                # Keep leading whitespace buffered while the following object
                # is still a possible tool envelope. A completed Responses
                # tool call has no message item, so that whitespace cannot be
                # emitted before we know whether it belongs to prose.
                if (
                    not self._emitted_parts
                    and not self._pending[:candidate_start].strip()
                ):
                    state = self._candidate_state(self._pending[candidate_start:])
                    if state in {"pending", "tool"}:
                        break
                deltas.append(self._emit_pending(candidate_start))
                continue
            state = self._candidate_state(self._pending)
            if state in {"pending", "tool"}:
                break
            deltas.append(self._emit_pending())
        return [delta for delta in deltas if delta]

    def _emit_pending(self, length: int | None = None) -> str:
        if length is None:
            length = len(self._pending)
        delta = self._pending[:length]
        self._pending = self._pending[length:]
        if delta:
            self._emitted_parts.append(delta)
        return delta

    def _candidate_start(self, text: str) -> int:
        previous_character = self.emitted_text[-1:] if self._emitted_parts else ""
        starts: list[int] = []
        for index, character in enumerate(text):
            if character == "{" and self._is_standalone_start(
                text, index, previous_character
            ):
                starts.append(index)
            if (
                character == "`"
                and text[index : index + 3] == "```"
                and self._is_standalone_start(text, index, previous_character)
            ):
                starts.append(index)
        return min(starts) if starts else -1

    @staticmethod
    def _is_standalone_start(
        text: str,
        index: int,
        previous_character: str,
    ) -> bool:
        preceding = text[index - 1] if index else previous_character
        return not preceding or preceding.isspace()

    def _candidate_state(self, text: str) -> str:
        if text.startswith("```"):
            return self._fenced_candidate_state(text)
        return self._json_candidate_state(text)

    def _json_candidate_state(self, text: str) -> str:
        if not text.startswith("{"):
            return "text"
        object_prefix = text[1:].lstrip()
        if not object_prefix:
            return "pending"
        if not object_prefix.startswith('"'):
            return "text"
        candidate_keys = self._TOOL_ENVELOPE_KEYS | self._NATIVE_FUNCTION_CALL_KEYS
        for key in candidate_keys:
            encoded_key = json.dumps(key)
            if encoded_key.startswith(object_prefix):
                return (
                    "pending" if len(text) < self._MAX_PENDING_PREFIX_CHARS else "text"
                )
        try:
            key, key_end = json.JSONDecoder().raw_decode(object_prefix)
        except json.JSONDecodeError:
            return "text"
        if key not in candidate_keys:
            return "text"
        remainder = object_prefix[key_end:].lstrip()
        if not remainder:
            return "pending"
        if not remainder.startswith(":"):
            return "text"
        if key in self._TOOL_ENVELOPE_KEYS:
            return "tool"

        # Native function-call items do not have a stable first key. Retain
        # candidates whose first field is one of the native item fields until
        # the complete object tells us whether it is actually a function call.
        try:
            payload, _ = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            return (
                "pending"
                if len(text) < self._MAX_PENDING_NATIVE_FUNCTION_CALL_CHARS
                else "text"
            )
        return "tool" if _tool_calls_from_envelope_payload(payload) else "text"

    def _fenced_candidate_state(self, text: str) -> str:
        match = re.match(r"```(?i:json)?[ \t]*\r?\n", text)
        if match is None:
            return "pending" if len(text) < self._MAX_PENDING_PREFIX_CHARS else "text"
        body = text[match.end() :]
        if not body:
            return "pending"
        return self._json_candidate_state(body)


def _response_output_items(
    *,
    text: str,
    tool_calls: list[dict[str, Any]],
    output_item_id: str = "",
) -> list[dict[str, Any]]:
    message_item = {
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
    if tool_calls:
        return ([message_item] if text else []) + [dict(item) for item in tool_calls]
    return [message_item]


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
    requested_max_tokens: int | None
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
    selected_alias = MODEL_ALIASES.get(requested_alias, requested_alias)
    compiled_selection = explicit_cloud_selection_for_model(selected_alias)
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
        selected_alias,
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
        attribution={
            "requested_alias": requested_alias,
            "selected_alias": selected_alias,
        },
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
    elapsed_ms: int | None = None,
    heartbeat: bool = False,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema": CLOUD_FALLBACK_SCHEMA,
        "state": state,
        "fallback_attempted": True,
        "local_failure_code": local_error.code,
        "fallback_provider": plan.provider,
        "fallback_model": plan.model,
        "request_id": invocation.invocation_id,
    }
    if elapsed_ms is not None:
        metadata["elapsed_ms"] = max(0, min(int(elapsed_ms), 3600000))
    if heartbeat:
        metadata["heartbeat"] = True
    return metadata


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
            "output_token_budget": {
                "requested": invocation.requested_max_tokens,
                "effective": invocation.max_tokens,
                "maximum": MAX_FACADE_TOKENS,
            },
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
    elapsed_ms: int | None = None,
    heartbeat: bool = False,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema": EXPLICIT_CLOUD_SELECTION_SCHEMA,
        "state": state,
        "requested_alias": plan.requested_alias,
        "provider": plan.provider,
        "model": plan.model,
        "lane": plan.lane,
        "request_id": invocation.invocation_id,
    }
    if elapsed_ms is not None:
        metadata["elapsed_ms"] = max(0, min(int(elapsed_ms), 3600000))
    if heartbeat:
        metadata["heartbeat"] = True
    return metadata


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
    native_responses_transport: bool = False,
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
            "norman_native_mantle_responses_transport": native_responses_transport,
            **invocation.trusted_context,
        },
        responses_options=(
            _native_mantle_responses_options(provider_payload)
            if native_responses_transport
            else {}
        ),
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
    native_responses_transport: bool = False,
) -> dict[str, Any]:
    """Run a user-selected cloud model without probing local capacity."""

    try:
        result = BedrockModelAdapter().invoke(
            _explicit_cloud_selection_request(
                plan=plan,
                invocation=invocation,
                messages=messages,
                provider_payload=provider_payload,
                native_responses_transport=native_responses_transport,
            )
        )
    except Exception as exc:
        safe_error_metadata = getattr(exc, "safe_metadata", None)
        safe_error_metadata = (
            safe_error_metadata() if callable(safe_error_metadata) else {}
        )
        safe_error_metadata = (
            safe_error_metadata if isinstance(safe_error_metadata, Mapping) else {}
        )
        logger.warning(
            "Norman explicit cloud selection failed request_id=%s provider=%s "
            "model=%s exception_class=%s http_status=%s "
            "provider_error_type=%s provider_error_code=%s provider_error_param=%s",
            invocation.invocation_id,
            plan.provider,
            plan.model,
            type(exc).__name__,
            safe_error_metadata.get("http_status", ""),
            safe_error_metadata.get("provider_error_type", ""),
            safe_error_metadata.get("provider_error_code", ""),
            safe_error_metadata.get("provider_error_param", ""),
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
    native_function_calls = (
        _native_mantle_function_call_items(result.raw)
        if native_responses_transport
        else []
    )
    native_response_output_items = (
        _native_mantle_response_output_items(result.raw)
        if native_responses_transport
        else []
    )
    if not result.text and not native_function_calls:
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
                "message": {
                    "role": "assistant",
                    "content": result.text,
                    "_norman_native_function_call_items": native_function_calls,
                    "_norman_native_response_output_items": (
                        native_response_output_items
                    ),
                },
                "finish_reason": "tool_calls" if native_function_calls else "stop",
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
            "output_token_budget": {
                "requested": invocation.requested_max_tokens,
                "effective": invocation.max_tokens,
                "maximum": MAX_FACADE_TOKENS,
            },
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
        max_tokens=_facade_max_tokens(provider_payload),
        requested_max_tokens=_requested_output_token_budget(provider_payload),
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
    max_tokens = _facade_max_tokens(provider_payload)
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
        requested_max_tokens=_requested_output_token_budget(provider_payload),
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
            "output_token_budget": {
                "requested": invocation.requested_max_tokens,
                "effective": invocation.max_tokens,
                "maximum": MAX_FACADE_TOKENS,
            },
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
    native_responses_transport: bool = False,
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
            native_responses_transport=native_responses_transport,
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


def _resolve_tool_continuation_response(
    *,
    prepared: PreparedResponsesExecution,
    chat_response: Mapping[str, Any],
    request_id: str,
) -> tuple[dict[str, Any], str, int]:
    """Apply one bounded repair when a completed tool call is repeated."""

    resolved = dict(chat_response)
    repeats_successful_call = _repeats_successful_tool_call(
        _choice_text(resolved),
        prepared=prepared,
    )
    if not repeats_successful_call:
        return resolved, "normal", 0
    if prepared.bridge_mode != GOVERNED_BRIDGE_MODE:
        return resolved, "passthrough", 0

    repaired = _execute_authorized_chat(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        messages=_tool_continuation_repair_messages(prepared.messages),
        request_id=f"{request_id}-tool-continuation-repair",
        native_responses_transport=prepared.native_responses_transport,
    )
    if _repeats_successful_tool_call(
        _choice_text(repaired),
        prepared=prepared,
    ):
        raise _tool_continuation_exhausted_error(prepared)
    return repaired, "repaired", 1


def _open_authorized_chat_stream(
    *,
    provider_payload: Mapping[str, Any],
    messages: list[dict[str, Any]],
    invocation: AuthorizedChatInvocation,
) -> norllama_gateway.NorllamaTextStream:
    """Open the already-authorized local stream or classify its failure."""

    try:
        return norllama_gateway.invoke_text_chat_stream(
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
        raise _classified_gateway_error(
            exc,
            request_id=invocation.invocation_id,
            requested_model=_requested_model(provider_payload),
            selected_model=invocation.authorization.model,
        ) from exc


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
    function_calls: dict[str, str]
    function_call_items: dict[str, dict[str, Any]]
    tool_outputs: set[tuple[str, str]]
    tool_chain_context: ToolChainContext
    history_replayed: bool
    client_metadata_ignored: bool
    store_requested: bool
    bridge_mode: str
    native_responses_transport: bool


def _prepare_responses_execution(
    payload: Mapping[str, Any],
    *,
    trusted_context: Mapping[str, Any] | None = None,
) -> PreparedResponsesExecution:
    _validate_supported_responses_fields(payload)
    provider_payload = _prepare_payload(payload)
    reasoning_advisory = _responses_reasoning_advisory(provider_payload)
    include_advisory = _responses_include_advisory(provider_payload)
    client_metadata_ignored = _responses_client_metadata_ignored(provider_payload)
    store_requested = _responses_store_requested(provider_payload)
    bridge_mode = _responses_bridge_mode(provider_payload)
    native_responses_transport = _uses_native_mantle_responses(provider_payload)
    provider_payload.pop("client_metadata", None)
    provider_payload.pop("store", None)
    history = _previous_response_history(
        _clean(provider_payload.get("previous_response_id")),
        compact=not native_responses_transport,
    )
    function_call_items = _validate_response_tool_continuation(
        provider_payload,
        known_function_call_items=history.function_call_items,
        known_tool_outputs=history.tool_outputs,
    )
    function_calls = {
        call_id: _clean(function_call.get("name"))
        for call_id, function_call in function_call_items.items()
        if _clean(function_call.get("name"))
    }
    tool_outputs = history.tool_outputs | _response_input_tool_outputs(provider_payload)
    tool_chain_context = _tool_chain_context(
        provider_payload,
        function_call_items=function_call_items,
        known_tool_outputs=tool_outputs,
    )
    input_messages = response_input_to_messages(
        provider_payload,
        known_tool_outputs=history.tool_outputs,
        known_function_call_items=history.function_call_items,
    )
    if native_responses_transport:
        # Mantle's Responses endpoint accepts the structured tool registry,
        # output format, reasoning configuration, and tool-call history
        # directly. Do not flatten them into the local text-adapter prompt.
        _structured_output_message(provider_payload)
        messages = [*history.messages, *input_messages]
    else:
        history_messages, tool_contract_messages = _messages_with_current_tool_contract(
            history.messages,
            provider_payload,
            bridge_mode=bridge_mode,
        )
        messages = [
            *history_messages,
            *tool_contract_messages,
            *_structured_output_message(provider_payload),
            *input_messages,
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
        previous_messages=history.messages,
        function_calls=function_calls,
        function_call_items=function_call_items,
        tool_outputs=tool_outputs,
        tool_chain_context=tool_chain_context,
        history_replayed=history.replayed,
        client_metadata_ignored=client_metadata_ignored,
        store_requested=store_requested,
        bridge_mode=bridge_mode,
        native_responses_transport=native_responses_transport,
    )


def _responses_response_from_chat(
    chat_response: Mapping[str, Any],
    *,
    prepared: PreparedResponsesExecution,
    response_id: str = "",
    created_at: int | None = None,
    output_item_id: str = "",
    normalized_output: NormalizedResponsesOutput | None = None,
    watchdog_state: str = "normal",
    watchdog_attempts: int = 0,
    store_response: bool = True,
) -> dict[str, Any]:
    provider_payload = prepared.provider_payload
    chat_response = dict(chat_response)
    text = _choice_text(chat_response)
    tools = _tools(provider_payload)
    native_function_calls = _messages(
        _choice_message(chat_response).get("_norman_native_function_call_items")
    )
    native_response_output_items = _messages(
        _choice_message(chat_response).get("_norman_native_response_output_items")
    )
    if prepared.native_responses_transport:
        tool_calls = [
            function_call
            for item in native_function_calls
            if (function_call := _function_call_item(item))
        ]
        visible_text = text
    else:
        preamble, tool_calls = _response_tool_calls(
            text,
            provider_payload=provider_payload,
            normalized_output=normalized_output,
        )
        visible_text = preamble if tool_calls else text
    output_items = (
        native_response_output_items
        if prepared.native_responses_transport and native_response_output_items
        else _response_output_items(
            text=visible_text,
            tool_calls=tool_calls,
            output_item_id=output_item_id,
        )
    )
    output_text = visible_text
    tool_chain = _tool_chain_telemetry(
        context=prepared.tool_chain_context,
        tool_calls=tool_calls,
        watchdog_state=watchdog_state,
        watchdog_attempts=watchdog_attempts,
    )
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
                "tools_declared": len(_tools(provider_payload)),
                "tool_calls_returned": len(tool_calls),
                "tool_chain": tool_chain,
                "tool_call_mode": (
                    "native_responses"
                    if prepared.native_responses_transport
                    and (_tool_names(tools) or tool_calls)
                    else "adapter_json_envelope"
                    if _tool_names(tools) or tool_calls
                    else "none"
                ),
                "tool_bridge_mode": prepared.bridge_mode,
                "tool_transport": (
                    "bedrock_mantle_responses"
                    if prepared.native_responses_transport
                    else "local_text_adapter"
                ),
                "structured_output_requested": bool(
                    _mapping(provider_payload.get("text")).get("format")
                ),
                "reasoning_advisory": _responses_reasoning_advisory(provider_payload),
                "include_advisory": _responses_include_advisory(provider_payload),
                "client_metadata_ignored": prepared.client_metadata_ignored,
                "store_requested": prepared.store_requested,
                "state_retention": (
                    "session" if prepared.store_requested else "ephemeral"
                ),
            },
        },
    }
    if store_response:
        function_call_items = dict(prepared.function_call_items)
        function_call_items.update(_function_call_items_from_items(output_items))
        _store_response_state(
            response_id,
            messages=prepared.messages,
            output_text=output_text,
            function_call_items=function_call_items,
            response_function_call_items=[
                item
                for item in output_items
                if _clean(item.get("type")) == "function_call"
            ],
            native_response_output_items=(
                native_response_output_items
                if prepared.native_responses_transport
                else None
            ),
            tool_outputs=prepared.tool_outputs,
            ephemeral=not prepared.store_requested,
        )
    return response


class FacadeResponsesStream:
    """A deferred local response stream with final facade response assembly."""

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
        self._completed_chat_response: dict[str, Any] | None = None
        self._cloud_fallback_attempted = False
        self._watchdog_state = "normal"
        self._watchdog_attempts = 0
        self._buffer_tool_continuation = (
            prepared.bridge_mode == GOVERNED_BRIDGE_MODE
            and bool(prepared.tool_chain_context.successful_call_signatures)
        )

    @property
    def model(self) -> str:
        if self._completed_chat_response is not None:
            return (
                _clean(self._completed_chat_response.get("model"))
                or self.invocation.authorization.model
            )
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

    def _local_stream_open_metadata(
        self,
        *,
        state: str,
        elapsed_ms: int,
        heartbeat: bool,
    ) -> dict[str, Any]:
        return {
            "schema": "norman.local-stream-open.v1",
            "state": state,
            "model": self.invocation.authorization.model,
            "elapsed_ms": max(0, min(int(elapsed_ms), 3600000)),
            "heartbeat": heartbeat,
        }

    def _open_local_stream_events(self):
        started_at = time.monotonic()
        self.stream = yield from _run_local_stream_open_with_progress(
            operation=lambda: _open_authorized_chat_stream(
                provider_payload=self.prepared.route_payload,
                messages=self.prepared.messages,
                invocation=self.invocation,
            ),
            progress_event=lambda state, elapsed_ms: {
                "type": "local_stream_open",
                "local_stream_open": self._local_stream_open_metadata(
                    state=state,
                    elapsed_ms=elapsed_ms,
                    heartbeat=True,
                ),
            },
        )
        self._stream_admission = self._admission_metadata_from_headers()
        yield {
            "type": "local_stream_open",
            "local_stream_open": self._local_stream_open_metadata(
                state="ready",
                elapsed_ms=max(0, int((time.monotonic() - started_at) * 1000)),
                heartbeat=False,
            ),
        }

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

    def _resolve_tool_continuation_response(
        self,
        chat_response: Mapping[str, Any],
    ) -> dict[str, Any]:
        (
            self._completed_chat_response,
            self._watchdog_state,
            self._watchdog_attempts,
        ) = _resolve_tool_continuation_response(
            prepared=self.prepared,
            chat_response=chat_response,
            request_id=self.invocation.invocation_id,
        )
        return dict(self._completed_chat_response)

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
        self._cloud_chat_response = yield from _run_cloud_invocation_with_progress(
            operation=lambda: _execute_cloud_fallback(
                plan=plan,
                provider_payload=self.prepared.route_payload,
                route_envelope=self.prepared.route_envelope,
                messages=self.prepared.messages,
                invocation=self.invocation,
                local_error=local_error,
            ),
            progress_event=lambda state, elapsed_ms: {
                "type": "cloud_fallback",
                "cloud_fallback": _cloud_fallback_metadata(
                    plan=plan,
                    invocation=self.invocation,
                    local_error=local_error,
                    state=state,
                    elapsed_ms=elapsed_ms,
                    heartbeat=True,
                ),
            },
        )
        chat_response = self._resolve_tool_continuation_response(
            self._cloud_chat_response
        )
        text = _choice_text(chat_response)
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
            self._cloud_chat_response = yield from _run_cloud_invocation_with_progress(
                operation=lambda: _execute_explicit_cloud_selection(
                    plan=self.explicit_cloud_plan,
                    provider_payload=self.prepared.route_payload,
                    route_envelope=self.prepared.route_envelope,
                    messages=self.prepared.messages,
                    invocation=self.invocation,
                    native_responses_transport=(
                        self.prepared.native_responses_transport
                    ),
                ),
                progress_event=lambda state, elapsed_ms: {
                    "type": "explicit_cloud_selection",
                    "explicit_cloud_selection": _explicit_cloud_selection_metadata(
                        plan=self.explicit_cloud_plan,
                        invocation=self.invocation,
                        state=state,
                        elapsed_ms=elapsed_ms,
                        heartbeat=True,
                    ),
                },
            )
            chat_response = self._resolve_tool_continuation_response(
                self._cloud_chat_response
            )
            text = _choice_text(chat_response)
            if text:
                yield {"type": "text", "text": text}
            return
        if self.pending_local_error is not None:
            yield from self._cloud_fallback_events(self.pending_local_error)
            return
        if self.stream is None:
            try:
                yield from self._open_local_stream_events()
            except Exception as exc:
                yield from self._cloud_fallback_events(self.classify_error(exc))
                return

        emitted_local_text = False
        buffered_text_parts: list[str] = []
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
                    if self._buffer_tool_continuation:
                        buffered_text_parts.append(event["text"])
                        continue
                    emitted_local_text = True
                yield event
        except Exception as exc:
            local_error = self.classify_error(exc)
            if emitted_local_text:
                raise local_error from exc
            yield from self._cloud_fallback_events(local_error)
            return

        if self._buffer_tool_continuation and buffered_text_parts:
            chat_response = _complete_authorized_chat(
                provider_payload=self.prepared.route_payload,
                route_envelope=self.prepared.route_envelope,
                messages=self.prepared.messages,
                invocation=self.invocation,
                result=self.stream.result("".join(buffered_text_parts)),
            )
            resolved = self._resolve_tool_continuation_response(chat_response)
            text = _choice_text(resolved)
            if text:
                yield {"type": "text", "text": text}
            return

        if not emitted_local_text:
            yield from self._cloud_fallback_events(self._empty_local_response_error())

    def iter_text(self):
        for event in self.iter_events():
            if event.get("type") == "text":
                fragment = event.get("text")
                if isinstance(fragment, str) and fragment:
                    yield fragment

    def complete(
        self,
        text: str,
        *,
        normalized_output: NormalizedResponsesOutput | None = None,
    ) -> dict[str, Any]:
        if self._completed_chat_response is not None:
            chat_response = dict(self._completed_chat_response)
        elif self._cloud_chat_response is not None:
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
            chat_response = self._resolve_tool_continuation_response(chat_response)
        norman = _mapping(chat_response.get("norman"))
        if self._cloud_chat_response is None:
            norman["streaming_mode"] = (
                "buffered_sse" if self._buffer_tool_continuation else "incremental_sse"
            )
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
            normalized_output=normalized_output,
            watchdog_state=self._watchdog_state,
            watchdog_attempts=self._watchdog_attempts,
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
    facade_request_id = request_id or f"norman-openai-response-{uuid.uuid4().hex}"
    chat_response = _execute_authorized_chat(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        messages=prepared.messages,
        request_id=facade_request_id,
        native_responses_transport=prepared.native_responses_transport,
    )
    (
        chat_response,
        watchdog_state,
        watchdog_attempts,
    ) = _resolve_tool_continuation_response(
        prepared=prepared,
        chat_response=chat_response,
        request_id=facade_request_id,
    )
    return _responses_response_from_chat(
        chat_response,
        prepared=prepared,
        watchdog_state=watchdog_state,
        watchdog_attempts=watchdog_attempts,
    )


def open_openai_responses_stream(
    payload: Mapping[str, Any],
    *,
    request_id: str = "",
    trusted_context: Mapping[str, Any] | None = None,
) -> FacadeResponsesStream:
    """Authorize a response stream before its local upstream is opened."""

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
    invocation = _prepare_authorized_chat_invocation(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        request_id=request_id or f"norman-openai-response-{uuid.uuid4().hex}",
    )
    return FacadeResponsesStream(
        prepared=prepared,
        invocation=invocation,
        stream=None,
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
