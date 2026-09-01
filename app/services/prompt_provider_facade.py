from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import requests

from app.core.config import settings
from app.core.estate_registry import worker_id_from_endpoint
from app.services.console_runtime.adapters.bedrock import BedrockModelAdapter
from app.services.console_runtime.types import ModelBudget, ModelRequest, ModelResult
from app.services.completion_contract import (
    response_has_substantive_content,
    response_promises_unfinished_work,
    sanitize_assistant_text,
)
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
MAX_RESPONSES_INLINE_IMAGE_BYTES = 20 * 1024 * 1024
RESPONSES_IMAGE_MEDIA_TYPES = {
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
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
TOOL_OUTPUT_FAILURE_MARKERS = (
    "access denied",
    "permission denied",
    "unauthorized",
    "forbidden",
    "execution_not_allowed",
    "tool failed",
    "failed to execute",
)
CODEX_IMPLICIT_TUI_TOOLS = (
    {
        "name": "exec_command",
        "type": "function",
        "description": (
            "Run a shell command in the current workspace and return its output. "
            "Use this to inspect files, repository state, local configuration, "
            "or command results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "yield_time_ms": {"type": "integer", "minimum": 1},
                "max_output_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["cmd"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_patch",
        "type": "function",
        "description": (
            "Apply a unified patch to workspace files. Use only after inspecting "
            "the relevant files and only for the requested change."
        ),
        "parameters": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
)
CLOUD_STREAM_HEARTBEAT_INTERVAL_SECONDS = 5.0
CLOUD_STREAM_MAX_ACTIVE_INVOCATIONS = 4
LOCAL_STREAM_OPEN_HEARTBEAT_INTERVAL_SECONDS = 5.0
LOCAL_STREAM_OPEN_MAX_ACTIVE_INVOCATIONS = 4
logger = logging.getLogger(__name__)
MODEL_ALIASES = {
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
) -> None:
    if not response_id:
        return
    stored_messages = [dict(message) for message in messages]
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
    calls.update(_function_calls_from_items(_messages(state.get("messages"))))
    return calls


def _function_call_items_from_state(
    state: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    calls = _function_call_items_from_items(_messages(state.get("function_calls")))
    calls.update(_function_call_items_from_items(_messages(state.get("output_items"))))
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


def _previous_response_history(previous_response_id: str) -> ResponseHistory:
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
    existing_call_ids = {
        _clean(message.get("call_id"))
        for message in messages
        if _clean(message.get("type")) == "function_call"
    }
    for call_id, function_call in function_call_items.items():
        if call_id not in existing_call_ids:
            messages.append(_function_call_context_message(function_call))
    return ResponseHistory(
        messages,
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
    return worker_id_from_endpoint(value)


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


def _namespace_member_name(namespace: str, member: Mapping[str, Any]) -> str:
    member_type = _clean(member.get("type"))
    if member_type and member_type != "function":
        return ""
    member_name = _tool_name(member)
    if not member_name:
        return ""
    canonical_prefix = f"{namespace}__"
    if member_name.startswith(canonical_prefix):
        return member_name.removeprefix(canonical_prefix)
    dotted_prefix = f"{namespace}."
    if member_name.startswith(dotted_prefix):
        return member_name.removeprefix(dotted_prefix)
    return member_name


def _canonical_tool_call_name(
    name: str,
    *,
    tools: list[dict[str, Any]],
    declared_names: set[str],
) -> str:
    """Normalize qualified namespace calls to Codex's executable member name."""

    if name in declared_names:
        return name
    for tool in tools:
        if _clean(tool.get("type")) != "namespace":
            continue
        namespace = _clean(tool.get("name"))
        if not namespace:
            continue
        for prefix in (f"{namespace}.", f"{namespace}__"):
            if not name.startswith(prefix):
                continue
            candidate = name.removeprefix(prefix)
            if candidate in declared_names:
                return candidate
    return name


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
    """Split assistant prose from one or more JSON tool envelopes.

    Some local models announce an action before emitting the tool JSON. The
    preferred contract is one complete, standalone final object. A small class
    of local-model failures instead emits several standalone envelopes, or adds
    prose after an otherwise valid envelope. Recover those calls without
    exposing their wire representation as assistant text. Ordinary JSON objects
    remain text because only recognized tool-envelope payloads are removed.
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
    return _standalone_json_tool_call_envelopes(text)


def _standalone_json_tool_call_envelopes(
    text: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Remove complete standalone tool envelopes from otherwise visible text."""

    decoder = json.JSONDecoder()
    visible_parts: list[str] = []
    calls: list[dict[str, Any]] = []
    cursor = 0
    search_from = 0
    while search_from < len(text):
        start = text.find("{", search_from)
        if start < 0:
            break
        if start and not text[start - 1].isspace():
            search_from = start + 1
            continue
        try:
            payload, length = decoder.raw_decode(text[start:])
        except (TypeError, ValueError):
            search_from = start + 1
            continue
        envelope_calls = _tool_calls_from_envelope_payload(payload)
        if not envelope_calls:
            search_from = start + max(1, length)
            continue
        visible_parts.append(text[cursor:start])
        calls.extend(envelope_calls)
        cursor = start + length
        search_from = cursor
    if not calls:
        return text, []
    visible_parts.append(text[cursor:])
    return "".join(visible_parts), calls


def _trailing_fenced_json_tool_call_envelope(text: str) -> tuple[str, str] | None:
    """Return the prose and JSON from a final generic or JSON fenced block."""

    match = re.fullmatch(
        r"(?s)(.*)```(?i:json)?[ \t]*\r?\n(.*?)\r?\n?```[ \t]*",
        text,
    )
    if match is None:
        return None
    return match.group(1), match.group(2)


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


def _tool_contract_definition(
    payload: Mapping[str, Any],
    *,
    implicit_tools: bool = False,
) -> list[dict[str, Any]]:
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
    if implicit_tools:
        declared_names = {_clean(tool.get("name")) for tool in compact}
        compact.extend(
            dict(tool)
            for tool in CODEX_IMPLICIT_TUI_TOOLS
            if _clean(tool.get("name")) not in declared_names
        )
    return compact


def _tool_contract_message(
    payload: Mapping[str, Any],
    *,
    bridge_mode: str = TRANSPARENT_BRIDGE_MODE,
    implicit_tools: bool = False,
) -> list[dict[str, Any]]:
    compact = _tool_contract_definition(payload, implicit_tools=implicit_tools)
    if not compact:
        return []
    if bridge_mode == GOVERNED_BRIDGE_MODE:
        content = (
            "When calling tools, return only one JSON object using either "
            '{"tool_call":{"name":"tool_name","arguments":{}}} or '
            '{"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
            "Never put prose before, between, or after tool JSON. If user "
            "confirmation is required, ask for it without emitting any tool "
            "JSON. Never duplicate an identical call. Put multiple calls in "
            "one tool_calls array only when every call is independently "
            "necessary; do not add exploratory workspace commands. "
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
            "Never put prose before, between, or after tool JSON. If user "
            "confirmation is required, ask for it without emitting any tool "
            "JSON. Never duplicate an identical call. Put multiple calls in "
            "one tool_calls array only when every call is independently "
            "necessary; do not add exploratory workspace commands. "
            "Use only a declared tool name. Do not reply with an intention to "
            "inspect, run, check, or edit something when the next useful step "
            "is a tool call; emit that call now. Available tools: "
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
    implicit_tools: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Preserve historical tool contracts and append a changed current registry.

    A Responses continuation may change its tool registry between turns. The
    prior registry remains part of the model history, while the new registry
    applies to the current turn. Rewriting an old contract makes historical
    function calls appear invalid and can cause the local model to repeat a
    completed tool call.
    """

    definition = _tool_contract_definition(payload, implicit_tools=implicit_tools)
    history = [dict(message) for message in messages]
    if not definition:
        return history, []
    latest_contract = next(
        (
            message
            for message in reversed(history)
            if _is_tool_contract_message(message)
        ),
        None,
    )
    if latest_contract and _message_has_tool_contract(
        latest_contract,
        definition=definition,
        bridge_mode=bridge_mode,
    ):
        return history, []
    return history, _tool_contract_message(
        payload,
        bridge_mode=bridge_mode,
        implicit_tools=implicit_tools,
    )


def _implicit_codex_tui_tools_required(
    payload: Mapping[str, Any],
    trusted_context: Mapping[str, Any] | None,
) -> bool:
    """Supply Codex's built-in tools when its Responses request omits them."""

    context = _mapping(trusted_context)
    return bool(_clean(context.get("source_tui") or context.get("gateway_route")))


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


def _inline_response_image(part: Mapping[str, Any]) -> tuple[bytes, str, str]:
    image_url = part.get("image_url")
    if not isinstance(image_url, str) or not image_url:
        raise FacadeError(
            "Responses image input requires an inline data URL",
            status_code=501,
            error_type="unsupported_parameter",
            code="unsupported_input_image_reference",
            param="input",
        )
    header, separator, encoded = image_url.partition(",")
    if (
        not separator
        or not header.lower().startswith("data:")
        or ";base64" not in header.lower()
    ):
        raise FacadeError(
            "Responses image input currently requires a base64 data URL",
            status_code=501,
            error_type="unsupported_parameter",
            code="unsupported_input_image_reference",
            param="input",
        )
    media_type = header[5:].split(";", 1)[0].strip().lower()
    extension = RESPONSES_IMAGE_MEDIA_TYPES.get(media_type)
    if not extension:
        raise FacadeError(
            f"Unsupported Responses image media type: {media_type or '<blank>'}",
            status_code=400,
            code="unsupported_input_image_media_type",
            param="input",
        )
    max_encoded_size = ((MAX_RESPONSES_INLINE_IMAGE_BYTES + 2) // 3) * 4
    if len(encoded) > max_encoded_size:
        raise FacadeError(
            "Responses image input exceeds Norman's 20 MiB inline image limit",
            status_code=413,
            code="input_image_too_large",
            param="input",
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FacadeError(
            "Responses image input contains invalid base64 data",
            status_code=400,
            code="invalid_input_image",
            param="input",
        ) from exc
    if not content:
        raise FacadeError(
            "Responses image input is empty",
            status_code=400,
            code="invalid_input_image",
            param="input",
        )
    if len(content) > MAX_RESPONSES_INLINE_IMAGE_BYTES:
        raise FacadeError(
            "Responses image input exceeds Norman's 20 MiB inline image limit",
            status_code=413,
            code="input_image_too_large",
            param="input",
        )
    digest = hashlib.sha256(content).hexdigest()
    return content, f"responses-input-{digest[:12]}.{extension}", media_type


def _response_image_text(part: Mapping[str, Any]) -> str:
    content, filename, media_type = _inline_response_image(part)
    text = ""
    specialist_error: Exception | None = None
    try:
        result = norllama_gateway.ocr_document(
            content=content,
            filename=filename,
            media_type=media_type,
            base_url=str(getattr(settings, "llm_offline_base_url", "") or ""),
            api_key=str(getattr(settings, "llm_offline_api_key", "") or ""),
        )
    except (requests.RequestException, RuntimeError, TimeoutError) as exc:
        specialist_error = exc
    else:
        text = _clean(result.get("text"))
    if not text:
        try:
            completed = subprocess.run(
                ["tesseract", "stdin", "stdout"],
                input=content,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            if specialist_error is None:
                specialist_error = exc
        else:
            if completed.returncode == 0:
                specialist_error = None
                text = completed.stdout.decode("utf-8", errors="replace").strip()
            elif specialist_error is None:
                specialist_error = RuntimeError("Tesseract image extraction failed")
    if not text and specialist_error is not None:
        raise FacadeError(
            "Norman could not extract the inline image through its local vision lane",
            status_code=503,
            error_type="server_error",
            code="input_image_processing_unavailable",
            param="input",
        ) from specialist_error
    if not text:
        text = "[No text was detected in this image.]"
    return f"[Attached image, locally extracted]\n{text}"


def _text_part_text(part: Mapping[str, Any]) -> str:
    part_type = _clean(part.get("type"))
    if part_type in {"input_text", "text"}:
        text = part.get("text")
        return text if isinstance(text, str) else _clean(text)
    if part_type in {"output_text"}:
        text = part.get("text")
        return text if isinstance(text, str) else _clean(text)
    if part_type == "input_image":
        return _response_image_text(part)
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
        if previous and previous != function_call:
            raise FacadeError(
                "Responses input contains conflicting function_call items",
                status_code=400,
                code="function_call_mismatch",
                param="input",
            )
        function_calls[function_call["call_id"]] = function_call
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
        if known and (
            _clean(known.get("name")) != function_call["name"]
            or _function_call_arguments(known) != function_call["arguments"]
        ):
            raise FacadeError(
                "Responses function_call does not match its prior call_id",
                status_code=400,
                code="function_call_mismatch",
                param="input",
            )
        function_call_items[call_id] = function_call

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
                    if (
                        _clean(existing.get("name")) != function_call["name"]
                        or _function_call_arguments(existing)
                        != function_call["arguments"]
                    ):
                        raise FacadeError(
                            "Responses function_call does not match its prior call_id",
                            status_code=400,
                            code="function_call_mismatch",
                            param="input",
                        )
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
    reserved_call_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    names = _tool_names(tools)
    if allow_implicit_tools:
        names.update(_clean(tool.get("name")) for tool in CODEX_IMPLICIT_TUI_TOOLS)
    if not text or (not names and not allow_implicit_tools):
        return []
    if raw_calls is None:
        raw_calls = _json_tool_call_envelope(text)
    calls: list[dict[str, Any]] = []
    used_call_ids = set(reserved_call_ids or ())
    seen_signatures: set[tuple[str, str]] = set()
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        name = _canonical_tool_call_name(
            _clean(raw.get("name")),
            tools=tools,
            declared_names=names,
        )
        if not name:
            continue
        arguments = raw.get("arguments", {})
        if name not in names:
            continue
        signature = (name, _canonical_function_call_arguments(arguments))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        proposed_call_id = _clean(raw.get("call_id"))
        call_id = proposed_call_id
        while not call_id or call_id in used_call_ids:
            call_id = f"call_{uuid.uuid4().hex}"
        used_call_ids.add(call_id)
        call_id_was_remapped = bool(proposed_call_id and proposed_call_id != call_id)
        calls.append(
            {
                "id": ("" if call_id_was_remapped else _clean(raw.get("id")))
                or f"fc_{uuid.uuid4().hex}",
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
    allow_implicit_tools: bool = False,
    reserved_call_ids: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    tools = _tools(provider_payload)
    if normalized_output is not None and normalized_output.raw_text == text:
        preamble = normalized_output.visible_text
        raw_calls = [dict(call) for call in normalized_output.raw_tool_calls]
    else:
        preamble, raw_calls = _trailing_json_tool_call_envelope(text)
    return (
        preamble,
        _extract_tool_calls(
            text,
            tools=tools,
            # Some Codex TUI request forms keep their executable tool registry
            # client-side and omit a top-level Responses tools list. The TUI still
            # validates the returned call before it can execute anything.
            allow_implicit_tools=(
                allow_implicit_tools or "tools" not in provider_payload
            ),
            raw_calls=raw_calls,
            reserved_call_ids=reserved_call_ids,
        ),
    )


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
        allow_implicit_tools=prepared.implicit_tools,
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

_TOOL_REQUEST_PATTERN = re.compile(
    r"(?is)\b(?:call|check|execute|inspect|query|read|run|search|start|use)\b"
)
_LIVE_OPERATIONAL_STATUS_PATTERN = re.compile(
    r"(?is)(?:\bhow\s+(?:is|are)\b|\b(?:current|live)\b).{0,48}"
    r"\b(?:backlogs?|deployments?|health|incidents?|production|queues?|services?|"
    r"systems?|workers?)\b"
    r"|\b(?:backlogs?|deployments?|incidents?|queues?|workers?)\b.{0,48}"
    r"\b(?:going|health|status)\b"
)
_OPERATIONAL_BOOTSTRAP_TOOLS = frozenset(
    {
        "exec_command",
        "list_capabilities",
        "read_file",
        "route_question",
        "session_start",
        "shell",
        "tool_search",
    }
)
_TOOL_PROTOCOL_REPAIR_MESSAGE = (
    "Your prior response announced unfinished work and cannot be a final answer. "
    "If a tool is needed, emit exactly one JSON tool_call or tool_calls object now, "
    "with no prose before or after it. Otherwise return the substantive final answer "
    "with the requested outcome or an explicit human-input blocker. Do not describe "
    "an action you have not performed."
)
_LIVE_OPERATIONAL_TOOL_REPAIR_MESSAGE = (
    "The user explicitly requested current operational status, and the prior response "
    "did not provide tool-backed evidence. Emit exactly one available domain tool call "
    "now, with no prose before or after it. Honor any environment and bound identity "
    "already supplied in the conversation; do not ask the user to repeat them. Do not "
    "call shell, exec_command, or read_file merely to inspect more setup."
)
_NAMESPACE_DISCOVERY_REPAIR_MESSAGE = (
    "The requested remote namespace is deferred and is not executable yet. Emit "
    "exactly one tool_search call now for the relevant domain tool, with no prose "
    "before or after it. Do not call a namespace member until tool_search returns it."
)


def _tool_continuation_repair_messages(
    messages: list[dict[str, Any]],
    *,
    repair_message: str = _TOOL_CONTINUATION_REPAIR_MESSAGE,
) -> list[dict[str, Any]]:
    return [
        *messages,
        {"role": "system", "content": repair_message},
    ]


def _tool_intention_without_call(
    text: str,
    *,
    prepared: PreparedResponsesExecution,
    enforce_live_request: bool = True,
) -> bool:
    """Recognize unfinished promised work when the model could call a tool."""

    if not response_has_substantive_content(text):
        return False
    if not _tool_contract_definition(
        prepared.provider_payload,
        implicit_tools=prepared.implicit_tools,
    ):
        return False
    _, tool_calls = _response_tool_calls(
        text,
        provider_payload=prepared.provider_payload,
        allow_implicit_tools=prepared.implicit_tools,
    )
    if tool_calls:
        return False
    if response_promises_unfinished_work(text):
        return True
    if (
        not enforce_live_request
        or not _live_operational_status_requested(prepared)
        or not _domain_tool_contract_available(prepared)
    ):
        return False
    return not any(
        name not in _OPERATIONAL_BOOTSTRAP_TOOLS
        for name, _ in prepared.tool_chain_context.successful_call_signatures
    )


def _latest_user_text(prepared: PreparedResponsesExecution) -> str:
    for message in reversed(prepared.messages):
        if _clean(message.get("role")) != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _live_operational_status_requested(prepared: PreparedResponsesExecution) -> bool:
    """Recognize a request that needs current operational evidence."""

    return bool(_LIVE_OPERATIONAL_STATUS_PATTERN.search(_latest_user_text(prepared)))


def _domain_tool_contract_available(prepared: PreparedResponsesExecution) -> bool:
    """Return whether the caller supplied a non-local operational tool surface."""

    implicit_names = {_clean(tool.get("name")) for tool in CODEX_IMPLICIT_TUI_TOOLS}
    for tool in _tools(prepared.provider_payload):
        if _clean(tool.get("type")) == "namespace":
            return True
        name = _tool_name(tool)
        if name and name not in implicit_names:
            return True
    return False


def _namespace_discovery_required(prepared: PreparedResponsesExecution) -> bool:
    available_names = _tool_names(_tools(prepared.provider_payload))
    if prepared.implicit_tools:
        available_names.update(
            _clean(tool.get("name")) for tool in CODEX_IMPLICIT_TUI_TOOLS
        )
    has_deferred_tool = _domain_tool_contract_available(prepared)
    discovered = any(
        name == "tool_search"
        for name, _ in prepared.tool_chain_context.successful_call_signatures
    )
    return has_deferred_tool and "tool_search" in available_names and not discovered


def _premature_namespace_member_call(
    text: str,
    *,
    prepared: PreparedResponsesExecution,
) -> str:
    if not _namespace_discovery_required(prepared):
        return ""
    member_names: set[str] = set()
    implicit_names = {_clean(tool.get("name")) for tool in CODEX_IMPLICIT_TUI_TOOLS}
    for tool in _tools(prepared.provider_payload):
        if _clean(tool.get("type")) != "namespace":
            name = _tool_name(tool)
            if name and name != "tool_search" and name not in implicit_names:
                member_names.add(name)
            continue
        namespace = _clean(tool.get("name"))
        members = tool.get("tools")
        if not namespace or not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, Mapping):
                name = _namespace_member_name(namespace, member)
                if name:
                    member_names.add(name)
    _, calls = _response_tool_calls(
        text,
        provider_payload=prepared.provider_payload,
        allow_implicit_tools=prepared.implicit_tools,
    )
    return next(
        (
            _clean(call.get("name"))
            for call in calls
            if call.get("name") in member_names
        ),
        "",
    )


def _chat_response_with_text(
    response: Mapping[str, Any],
    text: str,
) -> dict[str, Any]:
    rewritten = dict(response)
    choices = [dict(choice) for choice in response.get("choices", [])]
    if not choices:
        choices = [{"message": {"content": text}}]
    else:
        message = _mapping(choices[0].get("message"))
        message["content"] = text
        choices[0]["message"] = message
    rewritten["choices"] = choices
    return rewritten


def _tool_use_requested(prepared: PreparedResponsesExecution) -> bool:
    """Return whether the current user turn explicitly implies tool-backed work."""

    available_tools = _tool_contract_definition(
        prepared.provider_payload,
        implicit_tools=prepared.implicit_tools,
    )
    if not available_tools:
        return False
    latest_user_text = _latest_user_text(prepared)
    lowered = latest_user_text.lower()
    if any(_clean(tool.get("name")).lower() in lowered for tool in available_tools):
        return True
    return bool(
        _TOOL_REQUEST_PATTERN.search(latest_user_text)
        or _LIVE_OPERATIONAL_STATUS_PATTERN.search(latest_user_text)
    )


def _tool_continuation_exhausted_error(
    prepared: PreparedResponsesExecution,
    *,
    code: str = "tool_continuation_exhausted",
) -> FacadeError:
    return FacadeError(
        "Tool response remained invalid after the bounded Norman repair.",
        status_code=502,
        error_type="server_error",
        code=code,
        norman={
            "retryable": code == "tool_protocol_repair_exhausted",
            "responses_compatibility": {
                "tool_chain": _tool_chain_telemetry(
                    context=prepared.tool_chain_context,
                    tool_calls=[],
                    outcome="invalid_or_unresolved",
                    watchdog_state="exhausted",
                    watchdog_attempts=1,
                )
            },
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
    unfinished_work = response_promises_unfinished_work(text)
    if unfinished_work:
        route_receipt["output_shape"] = "progress_only"
        route_receipt["verifier_result"] = "incomplete"
    route_receipt["receipt_audit"] = audit_route_receipt(route_receipt)
    route_receipt["completion_gate"] = {
        "gate_passed": receipt_completion_gate_passes(
            route_receipt,
            audit=route_receipt["receipt_audit"],
            require_verifier=True,
        ),
        "require_verifier": True,
        "unfinished_work_detected": unfinished_work,
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


def _tui_tool_contract_required(route_envelope: Mapping[str, Any]) -> bool:
    """Return whether the trusted request context belongs to a Codex TUI."""

    trusted_context = _mapping(route_envelope.get("trusted_gateway_context"))
    return bool(
        _clean(trusted_context.get("source_tui"))
        or _lower(trusted_context.get("policy_scope")).startswith("tui:")
    )


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

    if _tui_tool_contract_required(route_envelope):
        raise FacadeError(
            "This Codex route requires shell and filesystem tools. Use "
            "norman-code; it will use the approved cloud fallback when local "
            "coding capacity is unavailable.",
            status_code=400,
            error_type="invalid_request_error",
            code="tool_capable_model_required",
            param="model",
            norman={
                "selected_model": requested_alias,
                "required_model": "norman-code",
                "cloud_fallback": "automatic_for_retryable_local_failure",
            },
        )

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
        # GPT-5 models use the Bedrock Mantle Responses endpoint rather than
        # the Bedrock Converse API. Reuse the managed facade alias so the
        # adapter never needs a caller-provided credential setting.
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
    result_text = sanitize_assistant_text(result.text)
    if not response_has_substantive_content(result_text):
        _log_cloud_fallback_failure(
            category="non_substantive_response",
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
                "message": {"role": "assistant", "content": result_text},
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


def _explicit_cloud_timeout_seconds() -> int:
    for setting_name in (
        "prompt_facade_explicit_cloud_timeout_seconds",
        "console_runtime_bedrock_timeout_seconds",
        "llm_provider_timeout_seconds",
    ):
        try:
            timeout_seconds = int(float(getattr(settings, setting_name, 0) or 0))
        except (TypeError, ValueError):
            continue
        if timeout_seconds > 0:
            return max(1, min(timeout_seconds, 1800))
    return 1200


def _explicit_cloud_selection_request(
    *,
    plan: ExplicitCloudSelectionPlan,
    invocation: AuthorizedChatInvocation,
    messages: list[dict[str, Any]],
    provider_payload: Mapping[str, Any],
) -> ModelRequest:
    timeout_seconds = _explicit_cloud_timeout_seconds()
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


def _explicit_cloud_failure_code(exc: Exception) -> str:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return "explicit_cloud_selection_timeout"
        current = current.__cause__ or current.__context__
    return "explicit_cloud_selection_failed"


def _explicit_cloud_selection_error(
    *,
    plan: ExplicitCloudSelectionPlan,
    invocation: AuthorizedChatInvocation,
    code: str,
) -> FacadeError:
    message = (
        "The selected cloud model is not authorized"
        if code == "explicit_cloud_selection_not_authorized"
        else (
            "The selected cloud model timed out before completion"
            if code == "explicit_cloud_selection_timeout"
            else "The selected cloud model could not complete"
        )
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
            code=_explicit_cloud_failure_code(exc),
        ) from exc
    if result.stop_reason == "policy_blocked":
        raise _explicit_cloud_selection_error(
            plan=plan,
            invocation=invocation,
            code="explicit_cloud_selection_not_authorized",
        )
    result_text = sanitize_assistant_text(result.text)
    if not response_has_substantive_content(result_text):
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
                "message": {"role": "assistant", "content": result_text},
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
    raw_text = _choice_text(result)
    text = sanitize_assistant_text(raw_text)
    if not response_has_substantive_content(text):
        failure_code = (
            "empty_local_response" if not raw_text else "non_substantive_local_response"
        )
        raise FacadeError(
            "Local model returned no substantive user-visible content",
            status_code=502,
            error_type="server_error",
            code=failure_code,
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


def _resolve_tool_continuation_response(
    *,
    prepared: PreparedResponsesExecution,
    chat_response: Mapping[str, Any],
    request_id: str,
) -> tuple[dict[str, Any], str, int]:
    """Apply one bounded repair when a completed tool call is repeated."""

    resolved = dict(chat_response)
    premature_member = _premature_namespace_member_call(
        _choice_text(resolved),
        prepared=prepared,
    )
    if premature_member:
        return (
            _chat_response_with_text(
                resolved,
                _json_dumps(
                    {
                        "tool_call": {
                            "name": "tool_search",
                            "arguments": {"query": premature_member},
                        }
                    }
                ),
            ),
            "repaired",
            1,
        )
    repeats_successful_call = _repeats_successful_tool_call(
        _choice_text(resolved),
        prepared=prepared,
    )
    intention_without_call = _tool_intention_without_call(
        _choice_text(resolved),
        prepared=prepared,
    )
    if not repeats_successful_call and not intention_without_call:
        return resolved, "normal", 0
    if repeats_successful_call and prepared.bridge_mode != GOVERNED_BRIDGE_MODE:
        return resolved, "passthrough", 0

    if intention_without_call and _namespace_discovery_required(prepared):
        repair_message = _NAMESPACE_DISCOVERY_REPAIR_MESSAGE
    elif intention_without_call and _live_operational_status_requested(prepared):
        repair_message = _LIVE_OPERATIONAL_TOOL_REPAIR_MESSAGE
    elif intention_without_call:
        repair_message = _TOOL_PROTOCOL_REPAIR_MESSAGE
    else:
        repair_message = _TOOL_CONTINUATION_REPAIR_MESSAGE

    repaired = _execute_authorized_chat(
        provider_payload=prepared.route_payload,
        route_envelope=prepared.route_envelope,
        messages=_tool_continuation_repair_messages(
            prepared.messages,
            repair_message=repair_message,
        ),
        request_id=f"{request_id}-tool-protocol-repair",
    )
    if _repeats_successful_tool_call(
        _choice_text(repaired),
        prepared=prepared,
    ):
        raise _tool_continuation_exhausted_error(prepared)
    if _tool_intention_without_call(_choice_text(repaired), prepared=prepared):
        raise _tool_continuation_exhausted_error(
            prepared,
            code="tool_protocol_repair_exhausted",
        )
    return repaired, "repaired", 1


def _validate_authoritative_fallback_response(
    *,
    prepared: PreparedResponsesExecution,
    chat_response: Mapping[str, Any],
) -> dict[str, Any]:
    """Reject incomplete fallback output instead of handing it back to local repair."""

    text = _choice_text(chat_response)
    if _repeats_successful_tool_call(text, prepared=prepared):
        raise _tool_continuation_exhausted_error(prepared)
    if _tool_intention_without_call(
        text,
        prepared=prepared,
        enforce_live_request=False,
    ):
        raise _tool_continuation_exhausted_error(
            prepared,
            code="tool_protocol_repair_exhausted",
        )
    return dict(chat_response)


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
    implicit_tools: bool


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
    provider_payload.pop("client_metadata", None)
    provider_payload.pop("store", None)
    history = _previous_response_history(
        _clean(provider_payload.get("previous_response_id"))
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
    implicit_tools = _implicit_codex_tui_tools_required(
        provider_payload,
        trusted_context,
    )
    tool_chain_context = _tool_chain_context(
        provider_payload,
        function_call_items=function_call_items,
        known_tool_outputs=tool_outputs,
    )
    history_messages, tool_contract_messages = _messages_with_current_tool_contract(
        history.messages,
        provider_payload,
        bridge_mode=bridge_mode,
        implicit_tools=implicit_tools,
    )
    messages = [
        *history_messages,
        *tool_contract_messages,
        *_structured_output_message(provider_payload),
        *response_input_to_messages(
            provider_payload,
            known_tool_outputs=history.tool_outputs,
            known_function_call_items=history.function_call_items,
        ),
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
        implicit_tools=implicit_tools,
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
    preamble, tool_calls = _response_tool_calls(
        text,
        provider_payload=provider_payload,
        normalized_output=normalized_output,
        allow_implicit_tools=prepared.implicit_tools,
        reserved_call_ids=set(prepared.function_call_items),
    )
    visible_text = preamble if tool_calls else text
    output_items = _response_output_items(
        text=visible_text,
        tool_calls=tool_calls,
        output_item_id=output_item_id,
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
                    "adapter_json_envelope"
                    if _tool_names(tools) or tool_calls
                    else "none"
                ),
                "tool_bridge_mode": prepared.bridge_mode,
                "tool_transport": "local_text_adapter",
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
        ) or _tool_use_requested(prepared)

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
        chat_response = _validate_authoritative_fallback_response(
            prepared=self.prepared,
            chat_response=self._cloud_chat_response,
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
            try:
                resolved = self._resolve_tool_continuation_response(chat_response)
            except FacadeError as local_error:
                yield from self._cloud_fallback_events(local_error)
                return
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


def _resolve_responses_with_fallback(
    *,
    prepared: PreparedResponsesExecution,
    chat_response: Mapping[str, Any],
    request_id: str,
) -> tuple[dict[str, Any], str, int]:
    """Resolve a non-stream response and keep cloud fallback final-authoritative."""

    try:
        return _resolve_tool_continuation_response(
            prepared=prepared,
            chat_response=chat_response,
            request_id=request_id,
        )
    except FacadeError as local_error:
        plan = _cloud_fallback_plan(
            provider_payload=prepared.route_payload,
            route_envelope=prepared.route_envelope,
            local_error=local_error,
        )
        if plan is None:
            raise
        invocation = _prepare_authorized_chat_invocation(
            provider_payload=prepared.route_payload,
            route_envelope=prepared.route_envelope,
            request_id=request_id,
        )
        fallback = _execute_cloud_fallback(
            plan=plan,
            provider_payload=prepared.route_payload,
            route_envelope=prepared.route_envelope,
            messages=prepared.messages,
            invocation=invocation,
            local_error=local_error,
        )
        return (
            _validate_authoritative_fallback_response(
                prepared=prepared,
                chat_response=fallback,
            ),
            "cloud_fallback",
            1,
        )


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
    )
    (
        chat_response,
        watchdog_state,
        watchdog_attempts,
    ) = _resolve_responses_with_fallback(
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
