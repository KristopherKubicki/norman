from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from ipaddress import ip_address
from secrets import compare_digest
from typing import Any, Iterable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.prompt_load_balancer import prompt_load_balancer_capabilities
from app.services.prompt_provider_facade import (
    FacadeError,
    capacity_model_for,
    chat_completion_stream_chunks,
    cloud_fallback_execution_configured,
    execute_openai_chat_facade,
    execute_openai_responses_facade,
    open_openai_responses_stream,
)
from app.services.norllama import capacity as norllama_capacity
from app.services.norllama import mesh_cache as norllama_mesh_cache
from app.services.proxy_observability import (
    proxy_alerts,
    proxy_dashboard,
    proxy_events_snapshot,
    proxy_observability_summary,
    record_proxy_event,
)

router = APIRouter(tags=["openai_compat"])
logger = logging.getLogger(__name__)
MAX_PROXY_EVENT_CAPACITY_WINDOW = 200
CAPACITY_MESH_PROBE_TIMEOUT_SECONDS = 3.0
MAX_TOOL_ENVELOPE_PREFIX_CHARS = 256
GATEWAY_ROUTE_HEADER = "x-norman-gateway-route"
GATEWAY_ROUTE_IDS = frozenset(
    {
        "autocamera",
        "cloudagent",
        "compere",
        "control-plane",
        "earlybird",
        "glimpser",
        "gold-book",
        "housebot",
        "infra",
        "market-sizing",
        "networking",
        "norman",
        "parkergale",
        "theseus",
        "tmi-dashboards",
    }
)


class OpenAICompatRequest(BaseModel):
    model: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    input: Any = None
    prompt: Any = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    norman: dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _configured_proxy_token() -> str:
    return _clean(os.environ.get("NORMAN_PROMPT_PROXY_TOKEN"))


def _bearer_token(request: Request) -> str:
    header = _clean(request.headers.get("authorization"))
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def _is_loopback_client(request: Request) -> bool:
    client_host = _clean(getattr(request.client, "host", ""))
    if not client_host:
        return False
    try:
        parsed = ip_address(client_host)
    except ValueError:
        return False
    if parsed.is_loopback:
        return True
    return bool(getattr(parsed, "ipv4_mapped", None) and parsed.ipv4_mapped.is_loopback)


def _verify_gateway_route(request: Request) -> tuple[str, JSONResponse | None]:
    gateway_route = _clean(request.headers.get(GATEWAY_ROUTE_HEADER)).lower()
    if not gateway_route:
        return "", _openai_error(
            status_code=403,
            message="Norman gateway route identity is required",
            error_type="permission_error",
            code="gateway_route_required",
        )
    if gateway_route not in GATEWAY_ROUTE_IDS:
        return "", _openai_error(
            status_code=403,
            message="Norman gateway route identity is not recognized",
            error_type="permission_error",
            code="gateway_route_invalid",
        )
    if not _is_loopback_client(request):
        return "", _openai_error(
            status_code=403,
            message="Norman gateway route identity must be supplied by the front door",
            error_type="permission_error",
            code="gateway_route_untrusted",
        )
    return gateway_route, None


def _gateway_context(gateway_route: str) -> dict[str, str]:
    return {
        "gateway_route": gateway_route,
        "source_tui": gateway_route,
        "policy_scope": f"tui:{gateway_route}",
    }


def _openai_error(
    *,
    status_code: int,
    message: str,
    error_type: str,
    code: str,
    param: str | None = None,
    headers: dict[str, str] | None = None,
    norman: dict[str, Any] | None = None,
) -> JSONResponse:
    error = {
        "message": message,
        "type": error_type,
        "param": param,
        "code": code,
    }
    if norman:
        error["norman"] = norman
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"error": error},
    )


def _verify_proxy_token(request: Request) -> JSONResponse | None:
    configured = _configured_proxy_token()
    if not configured:
        return _openai_error(
            status_code=503,
            message="Norman OpenAI-compatible proxy token is not configured",
            error_type="server_error",
            code="proxy_token_not_configured",
        )
    if not compare_digest(_bearer_token(request), configured):
        return _openai_error(
            status_code=401,
            message="Could not validate Norman OpenAI-compatible proxy credentials",
            error_type="authentication_error",
            code="invalid_api_key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return None


def _facade_error_response(exc: FacadeError) -> JSONResponse:
    return _openai_error(
        status_code=exc.status_code,
        message=exc.message,
        error_type=exc.error_type,
        code=exc.code,
        param=exc.param,
        headers=dict(exc.headers),
        norman=dict(exc.norman),
    )


def _facade_error_payload(exc: FacadeError) -> dict[str, Any]:
    payload = {
        "message": exc.message,
        "type": exc.error_type,
        "param": exc.param,
        "code": exc.code,
    }
    if exc.norman:
        payload["norman"] = dict(exc.norman)
    return payload


def _facade_error_status(exc: FacadeError) -> str:
    if exc.error_type == "unsupported_parameter" or exc.code.startswith("unsupported"):
        return "unsupported"
    if exc.error_type == "policy_blocked" or "blocked" in exc.code:
        return "blocked"
    if exc.code.startswith("local_capacity_"):
        return "capacity_unavailable"
    if exc.code == "local_model_unavailable":
        return "model_unavailable"
    if exc.code == "local_model_timeout":
        return "local_timeout"
    if exc.code.startswith("local_gateway_"):
        return "local_gateway_error"
    return "error"


def _unexpected_facade_error(
    *,
    request: Request,
    endpoint: str,
    started_at: float,
    payload: dict[str, Any],
    gateway_route: str,
) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception(
        "Unexpected local OpenAI facade failure endpoint=%s request_id=%s gateway_route=%s",
        endpoint,
        request_id or "missing",
        gateway_route,
    )
    error = {
        "message": "Local Responses gateway encountered an unexpected error",
        "type": "server_error",
        "param": None,
        "code": "internal_error",
    }
    record_proxy_event(
        endpoint=endpoint,
        method=request.method,
        request_id=request_id,
        status="error",
        http_status=500,
        payload=payload,
        headers=_request_headers(request),
        response={"norman": {"gateway": _gateway_context(gateway_route)}},
        error=error,
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    return _openai_error(
        status_code=500,
        message=error["message"],
        error_type=error["type"],
        code=error["code"],
    )


def _request_id(request: Request) -> str:
    return (
        _clean(request.headers.get("x-request-id"))
        or _clean(request.headers.get("x-codex-request-id"))
        or _clean(request.headers.get("x-norman-request-id"))
    )


def _request_payload(request_body: OpenAICompatRequest) -> dict[str, Any]:
    payload = request_body.dict(exclude_none=True, exclude_defaults=True)
    for field in request_body.__fields_set__:
        if getattr(request_body, field, None) is None:
            payload[field] = None
    return payload


def _request_headers(request: Request) -> dict[str, str]:
    return {key: value for key, value in request.headers.items()}


def _record_auth_failure(
    *,
    request: Request,
    endpoint: str,
    started_at: float,
    response: JSONResponse,
    gateway_route: str = "",
) -> None:
    error_payload: dict[str, Any] = {"type": "authentication_error"}
    try:
        raw = json.loads(response.body.decode("utf-8")) if response.body else {}
        error_payload = (
            raw.get("error", error_payload) if isinstance(raw, dict) else error_payload
        )
    except (TypeError, ValueError):
        pass
    error_code = _clean(error_payload.get("code"))
    record_proxy_event(
        endpoint=endpoint,
        method=request.method,
        request_id=_request_id(request),
        status="gateway_rejected"
        if error_code.startswith("gateway_route_")
        else "auth_failed",
        http_status=response.status_code,
        headers=_request_headers(request),
        response={
            "norman": {
                "gateway_route": gateway_route,
                "gateway": _gateway_context(gateway_route) if gateway_route else {},
            }
        },
        latency_ms=(time.time() - started_at) * 1000.0,
        error=error_payload,
    )


def _authorize_gateway_request(
    *,
    request: Request,
    endpoint: str,
    started_at: float,
) -> tuple[str, JSONResponse | None]:
    gateway_route, gateway_error = _verify_gateway_route(request)
    if gateway_error is not None:
        _record_auth_failure(
            request=request,
            endpoint=endpoint,
            started_at=started_at,
            response=gateway_error,
        )
        return "", gateway_error
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        _record_auth_failure(
            request=request,
            endpoint=endpoint,
            started_at=started_at,
            response=auth_error,
            gateway_route=gateway_route,
        )
        return "", auth_error
    return gateway_route, None


def _sse(lines: Iterable[dict[str, Any]]) -> Iterable[str]:
    for line in lines:
        yield f"data: {json.dumps(line, separators=(',', ':'))}\n\n"
    yield "data: [DONE]\n\n"


def _codex_model_catalog() -> list[dict[str, Any]]:
    """Return the minimal Codex model catalog for the local facade."""
    common = {
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Low reasoning effort."},
            {"effort": "medium", "description": "Standard reasoning effort."},
            {"effort": "high", "description": "High reasoning effort."},
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "minimal_client_version": [0, 0, 0],
        "supported_in_api": True,
        "upgrade": None,
        "base_instructions": "",
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "truncation_policy": {"mode": "bytes", "limit": 128000},
        "supports_parallel_tool_calls": False,
        "supports_image_detail_original": False,
        "context_window": 128000,
        "experimental_supported_tools": [],
    }
    return [
        {
            **common,
            "slug": "norman-code",
            "display_name": "Norman Code",
            "description": "Norman local-first coding route.",
            "priority": 1,
        },
        {
            **common,
            "slug": "norman-local",
            "display_name": "Norman Local",
            "description": "Norman local text route.",
            "priority": 2,
        },
    ]


@router.get("/v1/models", response_model=None)
async def openai_compat_models(request: Request):
    started_at = time.time()
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/models",
        started_at=started_at,
    )
    if auth_error is not None:
        return auth_error
    capabilities = prompt_load_balancer_capabilities()
    codex_models = _codex_model_catalog()
    response = {
        "object": "list",
        "data": [
            {
                "id": "norman-code",
                "object": "model",
                "created": 0,
                "owned_by": "norman",
            },
            {
                "id": "norman-local",
                "object": "model",
                "created": 0,
                "owned_by": "norman",
            },
        ],
        "models": codex_models,
        "norman": {
            "schema": "norman.openai-compatible-models.v1",
            "base_url": "/v1",
            "local_first": True,
            "cloud_forwarding": False,
            "capabilities": capabilities,
            "gateway": _gateway_context(gateway_route),
        },
    }
    record_proxy_event(
        endpoint="/v1/models",
        method=request.method,
        request_id=_request_id(request),
        status="metadata",
        http_status=200,
        headers=_request_headers(request),
        response={
            "norman": {
                "local_execution": False,
                "cloud_forwarding": False,
                "gateway": _gateway_context(gateway_route),
            }
        },
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    return response


@router.get("/v1/norman/capacity", response_model=None)
async def openai_compat_capacity(request: Request, model: str = "norman-code"):
    """Return a non-invoking capacity check for a supported local model alias."""

    started_at = time.time()
    endpoint = "/v1/norman/capacity"
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint=endpoint,
        started_at=started_at,
    )
    if auth_error is not None:
        return auth_error
    try:
        requested_model, selected_model = capacity_model_for(model)
    except FacadeError as exc:
        record_proxy_event(
            endpoint=endpoint,
            method=request.method,
            request_id=_request_id(request),
            status=_facade_error_status(exc),
            http_status=exc.status_code,
            payload={"model": model},
            headers=_request_headers(request),
            error=_facade_error_payload(exc),
            latency_ms=(time.time() - started_at) * 1000.0,
        )
        return _facade_error_response(exc)

    try:
        mesh = await asyncio.wait_for(
            asyncio.to_thread(
                norllama_mesh_cache.get_mesh_overview,
                force_refresh=True,
                timeout_seconds=2,
            ),
            timeout=CAPACITY_MESH_PROBE_TIMEOUT_SECONDS,
        )
        snapshot = norllama_capacity.build_capacity_snapshot(
            mesh,
            requested_model=requested_model,
            selected_model=selected_model,
            route_outcomes=norllama_capacity.proxy_event_route_outcomes(
                proxy_events_snapshot(limit=MAX_PROXY_EVENT_CAPACITY_WINDOW)
            ),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Norman capacity probe timed out model=%s",
            selected_model,
        )
        snapshot = norllama_capacity.unavailable_capacity_snapshot(
            requested_model=requested_model,
            selected_model=selected_model,
            reason="mesh_probe_timeout",
        )
    except Exception:
        logger.warning(
            "Norman capacity probe failed model=%s", selected_model, exc_info=True
        )
        snapshot = norllama_capacity.unavailable_capacity_snapshot(
            requested_model=requested_model,
            selected_model=selected_model,
            reason="mesh_probe_failed",
        )
    snapshot["cloud_fallback"] = cloud_fallback_execution_configured()

    response = {
        **snapshot,
        "gateway": _gateway_context(gateway_route),
    }
    record_proxy_event(
        endpoint=endpoint,
        method=request.method,
        request_id=_request_id(request),
        status="capacity_available"
        if snapshot["available"]
        else "capacity_unavailable",
        http_status=200,
        payload={"model": requested_model},
        headers=_request_headers(request),
        response={
            "norman": {
                "gateway": _gateway_context(gateway_route),
                "capacity": snapshot,
            }
        },
        error={} if snapshot["available"] else {"code": snapshot["reason"]},
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    return response


@router.post("/v1/chat/completions", response_model=None)
async def openai_compat_chat_completions(
    request_body: OpenAICompatRequest,
    request: Request,
):
    started_at = time.time()
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/chat/completions",
        started_at=started_at,
    )
    if auth_error is not None:
        return auth_error
    request_payload = _request_payload(request_body)
    try:
        response = await asyncio.to_thread(
            execute_openai_chat_facade,
            request_payload,
            request_id=_request_id(request),
            trusted_context=_gateway_context(gateway_route),
        )
    except FacadeError as exc:
        record_proxy_event(
            endpoint="/v1/chat/completions",
            method=request.method,
            request_id=_request_id(request),
            status=_facade_error_status(exc),
            http_status=exc.status_code,
            payload=request_payload,
            headers=_request_headers(request),
            error=_facade_error_payload(exc),
            latency_ms=(time.time() - started_at) * 1000.0,
        )
        return _facade_error_response(exc)
    except Exception:
        return _unexpected_facade_error(
            request=request,
            endpoint="/v1/chat/completions",
            started_at=started_at,
            payload=request_payload,
            gateway_route=gateway_route,
        )
    record_proxy_event(
        endpoint="/v1/chat/completions",
        method=request.method,
        request_id=_request_id(request),
        status="success",
        http_status=200,
        payload=request_payload,
        response=response,
        headers=_request_headers(request),
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    if request_body.stream:
        return StreamingResponse(
            _sse(chat_completion_stream_chunks(response)),
            media_type="text/event-stream",
        )
    return response


def _response_sse_event(event_type: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )


def _tool_envelope_prefix_state(text: str) -> str:
    """Classify a buffered Responses tool-call envelope prefix.

    Local models emit a JSON envelope instead of native tool calls. Hold back
    only a possible first JSON key so a valid envelope is never streamed as
    assistant text before the completed response becomes a function_call.
    """

    if len(text) >= MAX_TOOL_ENVELOPE_PREFIX_CHARS:
        return "text"
    candidate = text.lstrip()
    if not candidate:
        return "pending"
    if not candidate.startswith("{"):
        return "text"
    object_prefix = candidate[1:].lstrip()
    if not object_prefix:
        return "pending"
    if not object_prefix.startswith('"'):
        return "text"
    try:
        key, key_end = json.JSONDecoder().raw_decode(object_prefix)
    except json.JSONDecodeError:
        return "pending"
    if key not in {"tool_call", "tool_calls"}:
        return "text"
    remainder = object_prefix[key_end:].lstrip()
    if not remainder:
        return "pending"
    return "tool" if remainder.startswith(":") else "text"


def _response_stream_snapshot(stream: Any, *, status: str) -> dict[str, Any]:
    snapshot = {
        "id": stream.response_id,
        "object": "response",
        "created_at": stream.created_at,
        "status": status,
        "model": stream.model,
        "output": [],
    }
    admission = stream.admission_metadata()
    if admission:
        snapshot["norman"] = {"stream_admission": admission}
    return snapshot


def _response_sse(stream: Any):
    """Translate the native Ollama stream into incremental Responses events."""

    initial = _response_stream_snapshot(stream, status="in_progress")
    text_parts: list[str] = []
    buffered_prefix = ""
    text_item_started = False
    tool_envelope = False

    def begin_text_item() -> Iterable[str]:
        nonlocal text_item_started
        if text_item_started:
            return
        text_item_started = True
        item = {
            "id": stream.output_item_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        yield _response_sse_event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": item,
            },
        )
        yield _response_sse_event(
            "response.content_part.added",
            {
                "type": "response.content_part.added",
                "item_id": stream.output_item_id,
                "output_index": 0,
                "content_index": 0,
                "part": {
                    "type": "output_text",
                    "text": "",
                    "annotations": [],
                },
            },
        )

    def text_delta(delta: str) -> str:
        return _response_sse_event(
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "item_id": stream.output_item_id,
                "output_index": 0,
                "content_index": 0,
                "delta": delta,
            },
        )

    try:
        yield _response_sse_event(
            "response.created",
            {"type": "response.created", "response": initial},
        )
        yield _response_sse_event(
            "response.in_progress",
            {"type": "response.in_progress", "response": initial},
        )
        for stream_event in stream.iter_events():
            if stream_event.get("type") == "admission":
                snapshot = _response_stream_snapshot(stream, status="in_progress")
                yield _response_sse_event(
                    "response.in_progress",
                    {
                        "type": "response.in_progress",
                        "response": snapshot,
                    },
                )
                continue
            if stream_event.get("type") == "cloud_fallback":
                cloud_fallback = stream_event.get("cloud_fallback")
                if isinstance(cloud_fallback, dict):
                    snapshot = _response_stream_snapshot(stream, status="in_progress")
                    norman = (
                        dict(snapshot.get("norman"))
                        if isinstance(snapshot.get("norman"), dict)
                        else {}
                    )
                    norman["cloud_fallback"] = dict(cloud_fallback)
                    snapshot["norman"] = norman
                    yield _response_sse_event(
                        "response.in_progress",
                        {
                            "type": "response.in_progress",
                            "response": snapshot,
                        },
                    )
                continue
            if stream_event.get("type") == "explicit_cloud_selection":
                selection = stream_event.get("explicit_cloud_selection")
                if isinstance(selection, dict):
                    snapshot = _response_stream_snapshot(stream, status="in_progress")
                    norman = (
                        dict(snapshot.get("norman"))
                        if isinstance(snapshot.get("norman"), dict)
                        else {}
                    )
                    norman["explicit_cloud_selection"] = dict(selection)
                    snapshot["norman"] = norman
                    yield _response_sse_event(
                        "response.in_progress",
                        {
                            "type": "response.in_progress",
                            "response": snapshot,
                        },
                    )
                continue
            if stream_event.get("type") != "text":
                continue
            fragment = stream_event.get("text")
            if not isinstance(fragment, str) or not fragment:
                continue
            text_parts.append(fragment)
            if not text_item_started:
                buffered_prefix += fragment
                prefix_state = _tool_envelope_prefix_state(buffered_prefix)
                if prefix_state == "pending":
                    continue
                if prefix_state == "tool":
                    tool_envelope = True
                    continue
                for event in begin_text_item():
                    yield event
                yield text_delta(buffered_prefix)
                buffered_prefix = ""
                continue
            if tool_envelope:
                continue
            for event in begin_text_item():
                yield event
            yield text_delta(fragment)

        text = "".join(text_parts)
        response = stream.complete(text)
        output = response.get("output")
        output_items = (
            [dict(item) for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )
        function_call_items = [
            (output_index, item)
            for output_index, item in enumerate(output_items)
            if item.get("type") == "function_call"
        ]
        if function_call_items:
            for output_index, output_item in function_call_items:
                arguments = output_item.get("arguments")
                arguments = arguments if isinstance(arguments, str) else ""
                in_progress_item = {
                    "type": "function_call",
                    "id": output_item.get("id"),
                    "status": "in_progress",
                    "call_id": output_item.get("call_id"),
                    "name": output_item.get("name"),
                    "arguments": "",
                }
                yield _response_sse_event(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "response_id": stream.response_id,
                        "output_index": output_index,
                        "item": in_progress_item,
                    },
                )
                if arguments:
                    yield _response_sse_event(
                        "response.function_call_arguments.delta",
                        {
                            "type": "response.function_call_arguments.delta",
                            "response_id": stream.response_id,
                            "item_id": output_item.get("id"),
                            "output_index": output_index,
                            "delta": arguments,
                        },
                    )
                yield _response_sse_event(
                    "response.function_call_arguments.done",
                    {
                        "type": "response.function_call_arguments.done",
                        "response_id": stream.response_id,
                        "item_id": output_item.get("id"),
                        "output_index": output_index,
                        "arguments": arguments,
                    },
                )
                yield _response_sse_event(
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "response_id": stream.response_id,
                        "output_index": output_index,
                        "item": output_item,
                    },
                )
        else:
            if not text_item_started:
                for event in begin_text_item():
                    yield event
                if text:
                    yield text_delta(text)
            final_item = output_items[0] if output_items else {}
            yield _response_sse_event(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": stream.output_item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": response.get("output_text")
                    if isinstance(response.get("output_text"), str)
                    else "",
                },
            )
            yield _response_sse_event(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": stream.output_item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": response.get("output_text")
                        if isinstance(response.get("output_text"), str)
                        else "",
                        "annotations": [],
                    },
                },
            )
            yield _response_sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": final_item,
                },
            )
        yield _response_sse_event(
            "response.completed",
            {"type": "response.completed", "response": response},
        )
        yield "data: [DONE]\n\n"
        return response, None
    except Exception as exc:
        error = stream.classify_error(exc)
        failed = _response_stream_snapshot(stream, status="failed")
        failed["error"] = _facade_error_payload(error)
        yield _response_sse_event(
            "response.failed",
            {"type": "response.failed", "response": failed},
        )
        yield "data: [DONE]\n\n"
        return None, error
    finally:
        stream.close()


@router.post("/v1/responses", response_model=None)
async def openai_compat_responses(
    request_body: OpenAICompatRequest,
    request: Request,
):
    started_at = time.time()
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/responses",
        started_at=started_at,
    )
    if auth_error is not None:
        return auth_error
    request_payload = _request_payload(request_body)
    if request_body.stream:
        try:
            stream = await asyncio.to_thread(
                open_openai_responses_stream,
                request_payload,
                request_id=_request_id(request),
                trusted_context=_gateway_context(gateway_route),
            )
        except FacadeError as exc:
            record_proxy_event(
                endpoint="/v1/responses",
                method=request.method,
                request_id=_request_id(request),
                status=_facade_error_status(exc),
                http_status=exc.status_code,
                payload=request_payload,
                headers=_request_headers(request),
                error=_facade_error_payload(exc),
                latency_ms=(time.time() - started_at) * 1000.0,
            )
            return _facade_error_response(exc)
        except Exception:
            return _unexpected_facade_error(
                request=request,
                endpoint="/v1/responses",
                started_at=started_at,
                payload=request_payload,
                gateway_route=gateway_route,
            )

        def response_events():
            terminal = False
            try:
                response, error = yield from _response_sse(stream)
                terminal = True
                if response is not None:
                    record_proxy_event(
                        endpoint="/v1/responses",
                        method=request.method,
                        request_id=_request_id(request),
                        status="success",
                        http_status=200,
                        payload=request_payload,
                        response=response,
                        headers=_request_headers(request),
                        latency_ms=(time.time() - started_at) * 1000.0,
                    )
                elif error is not None:
                    record_proxy_event(
                        endpoint="/v1/responses",
                        method=request.method,
                        request_id=_request_id(request),
                        status=_facade_error_status(error),
                        http_status=error.status_code,
                        payload=request_payload,
                        headers=_request_headers(request),
                        error=_facade_error_payload(error),
                        latency_ms=(time.time() - started_at) * 1000.0,
                    )
            finally:
                stream.close()
                if not terminal:
                    record_proxy_event(
                        endpoint="/v1/responses",
                        method=request.method,
                        request_id=_request_id(request),
                        status="client_disconnected",
                        http_status=499,
                        payload=request_payload,
                        headers=_request_headers(request),
                        error={"code": "client_disconnected"},
                        latency_ms=(time.time() - started_at) * 1000.0,
                    )

        return StreamingResponse(
            response_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    try:
        response = await asyncio.to_thread(
            execute_openai_responses_facade,
            request_payload,
            request_id=_request_id(request),
            trusted_context=_gateway_context(gateway_route),
        )
    except FacadeError as exc:
        record_proxy_event(
            endpoint="/v1/responses",
            method=request.method,
            request_id=_request_id(request),
            status=_facade_error_status(exc),
            http_status=exc.status_code,
            payload=request_payload,
            headers=_request_headers(request),
            error=_facade_error_payload(exc),
            latency_ms=(time.time() - started_at) * 1000.0,
        )
        return _facade_error_response(exc)
    except Exception:
        return _unexpected_facade_error(
            request=request,
            endpoint="/v1/responses",
            started_at=started_at,
            payload=request_payload,
            gateway_route=gateway_route,
        )
    record_proxy_event(
        endpoint="/v1/responses",
        method=request.method,
        request_id=_request_id(request),
        status="success",
        http_status=200,
        payload=request_payload,
        response=response,
        headers=_request_headers(request),
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    return response


@router.get("/v1/norman/proxy/events", response_model=None)
async def openai_compat_proxy_events(request: Request, limit: int = 100):
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/norman/proxy/events",
        started_at=time.time(),
    )
    if auth_error is not None:
        return auth_error
    return {
        "schema": "norman.proxy.events.v1",
        "gateway": _gateway_context(gateway_route),
        "events": proxy_events_snapshot(limit=limit),
    }


@router.get("/v1/norman/proxy/summary", response_model=None)
async def openai_compat_proxy_summary(request: Request, limit: int = 100):
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/norman/proxy/summary",
        started_at=time.time(),
    )
    if auth_error is not None:
        return auth_error
    return {
        **proxy_observability_summary(limit=limit),
        "gateway": _gateway_context(gateway_route),
    }


@router.get("/v1/norman/proxy/alerts", response_model=None)
async def openai_compat_proxy_alerts(request: Request, limit: int = 100):
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/norman/proxy/alerts",
        started_at=time.time(),
    )
    if auth_error is not None:
        return auth_error
    summary = proxy_observability_summary(limit=limit)
    return {
        **proxy_alerts(summary=summary),
        "gateway": _gateway_context(gateway_route),
    }


@router.get("/v1/norman/proxy/dashboard", response_model=None)
async def openai_compat_proxy_dashboard(request: Request, limit: int = 100):
    gateway_route, auth_error = _authorize_gateway_request(
        request=request,
        endpoint="/v1/norman/proxy/dashboard",
        started_at=time.time(),
    )
    if auth_error is not None:
        return auth_error
    return {
        **proxy_dashboard(limit=limit),
        "gateway": _gateway_context(gateway_route),
    }
