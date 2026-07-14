from __future__ import annotations

import json
import os
import time
from secrets import compare_digest
from typing import Any, Iterable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.prompt_load_balancer import prompt_load_balancer_capabilities
from app.services.prompt_provider_facade import (
    FacadeError,
    chat_completion_stream_chunks,
    execute_openai_chat_facade,
    execute_openai_responses_facade,
)
from app.services.proxy_observability import (
    proxy_alerts,
    proxy_dashboard,
    proxy_events_snapshot,
    proxy_observability_summary,
    record_proxy_event,
)

router = APIRouter(tags=["openai_compat"])


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


def _openai_error(
    *,
    status_code: int,
    message: str,
    error_type: str,
    code: str,
    param: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
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
    )


def _facade_error_payload(exc: FacadeError) -> dict[str, Any]:
    return {
        "message": exc.message,
        "type": exc.error_type,
        "param": exc.param,
        "code": exc.code,
    }


def _facade_error_status(exc: FacadeError) -> str:
    if exc.error_type == "unsupported_parameter" or exc.code.startswith("unsupported"):
        return "unsupported"
    if exc.error_type == "policy_blocked" or "blocked" in exc.code:
        return "blocked"
    return "error"


def _request_id(request: Request) -> str:
    return (
        _clean(request.headers.get("x-request-id"))
        or _clean(request.headers.get("x-codex-request-id"))
        or _clean(request.headers.get("x-norman-request-id"))
    )


def _request_payload(request_body: OpenAICompatRequest) -> dict[str, Any]:
    return request_body.dict(exclude_none=True, exclude_defaults=True)


def _request_headers(request: Request) -> dict[str, str]:
    return {key: value for key, value in request.headers.items()}


def _record_auth_failure(
    *,
    request: Request,
    endpoint: str,
    started_at: float,
    response: JSONResponse,
) -> None:
    error_payload: dict[str, Any] = {"type": "authentication_error"}
    try:
        raw = json.loads(response.body.decode("utf-8")) if response.body else {}
        error_payload = (
            raw.get("error", error_payload) if isinstance(raw, dict) else error_payload
        )
    except (TypeError, ValueError):
        pass
    record_proxy_event(
        endpoint=endpoint,
        method=request.method,
        request_id=_request_id(request),
        status="auth_failed",
        http_status=response.status_code,
        headers=_request_headers(request),
        latency_ms=(time.time() - started_at) * 1000.0,
        error=error_payload,
    )


def _sse(lines: Iterable[dict[str, Any]]) -> Iterable[str]:
    for line in lines:
        yield f"data: {json.dumps(line, separators=(',', ':'))}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/v1/models", response_model=None)
async def openai_compat_models(request: Request):
    started_at = time.time()
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        _record_auth_failure(
            request=request,
            endpoint="/v1/models",
            started_at=started_at,
            response=auth_error,
        )
        return auth_error
    capabilities = prompt_load_balancer_capabilities()
    response = {
        "object": "list",
        "data": [
            {
                "id": "norman-local",
                "object": "model",
                "created": 0,
                "owned_by": "norman",
            }
        ],
        "norman": {
            "schema": "norman.openai-compatible-models.v1",
            "base_url": "/v1",
            "local_first": True,
            "cloud_forwarding": False,
            "capabilities": capabilities,
        },
    }
    record_proxy_event(
        endpoint="/v1/models",
        method=request.method,
        request_id=_request_id(request),
        status="metadata",
        http_status=200,
        headers=_request_headers(request),
        response={"norman": {"local_execution": False, "cloud_forwarding": False}},
        latency_ms=(time.time() - started_at) * 1000.0,
    )
    return response


@router.post("/v1/chat/completions", response_model=None)
async def openai_compat_chat_completions(
    request_body: OpenAICompatRequest,
    request: Request,
):
    started_at = time.time()
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        _record_auth_failure(
            request=request,
            endpoint="/v1/chat/completions",
            started_at=started_at,
            response=auth_error,
        )
        return auth_error
    request_payload = _request_payload(request_body)
    try:
        response = execute_openai_chat_facade(
            request_payload,
            request_id=_request_id(request),
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


def _response_sse(response: dict[str, Any]) -> Iterable[str]:
    text = _clean(response.get("output_text"))
    response_id = _clean(response.get("id"))
    yield (
        "event: response.created\n"
        f"data: {json.dumps({'type': 'response.created', 'response_id': response_id}, separators=(',', ':'))}\n\n"
    )
    yield (
        "event: response.output_text.delta\n"
        f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': text, 'response_id': response_id}, separators=(',', ':'))}\n\n"
    )
    yield (
        "event: response.completed\n"
        f"data: {json.dumps({'type': 'response.completed', 'response': response}, separators=(',', ':'))}\n\n"
    )
    yield "data: [DONE]\n\n"


@router.post("/v1/responses", response_model=None)
async def openai_compat_responses(
    request_body: OpenAICompatRequest,
    request: Request,
):
    started_at = time.time()
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        _record_auth_failure(
            request=request,
            endpoint="/v1/responses",
            started_at=started_at,
            response=auth_error,
        )
        return auth_error
    request_payload = _request_payload(request_body)
    try:
        response = execute_openai_responses_facade(
            request_payload,
            request_id=_request_id(request),
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
    if request_body.stream:
        return StreamingResponse(
            _response_sse(response), media_type="text/event-stream"
        )
    return response


@router.get("/v1/norman/proxy/events", response_model=None)
async def openai_compat_proxy_events(request: Request, limit: int = 100):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    return {
        "schema": "norman.proxy.events.v1",
        "events": proxy_events_snapshot(limit=limit),
    }


@router.get("/v1/norman/proxy/summary", response_model=None)
async def openai_compat_proxy_summary(request: Request, limit: int = 100):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    return proxy_observability_summary(limit=limit)


@router.get("/v1/norman/proxy/alerts", response_model=None)
async def openai_compat_proxy_alerts(request: Request, limit: int = 100):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    summary = proxy_observability_summary(limit=limit)
    return proxy_alerts(summary=summary)


@router.get("/v1/norman/proxy/dashboard", response_model=None)
async def openai_compat_proxy_dashboard(request: Request, limit: int = 100):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    return proxy_dashboard(limit=limit)
