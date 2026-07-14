from __future__ import annotations

import json
import os
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


def _request_id(request: Request) -> str:
    return (
        _clean(request.headers.get("x-request-id"))
        or _clean(request.headers.get("x-codex-request-id"))
        or _clean(request.headers.get("x-norman-request-id"))
    )


def _request_payload(request_body: OpenAICompatRequest) -> dict[str, Any]:
    return request_body.dict(exclude_none=True, exclude_defaults=True)


def _sse(lines: Iterable[dict[str, Any]]) -> Iterable[str]:
    for line in lines:
        yield f"data: {json.dumps(line, separators=(',', ':'))}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/v1/models", response_model=None)
async def openai_compat_models(request: Request):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    capabilities = prompt_load_balancer_capabilities()
    return {
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


@router.post("/v1/chat/completions", response_model=None)
async def openai_compat_chat_completions(
    request_body: OpenAICompatRequest,
    request: Request,
):
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    try:
        response = execute_openai_chat_facade(
            _request_payload(request_body),
            request_id=_request_id(request),
        )
    except FacadeError as exc:
        return _facade_error_response(exc)
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
    auth_error = _verify_proxy_token(request)
    if auth_error is not None:
        return auth_error
    try:
        response = execute_openai_responses_facade(
            _request_payload(request_body),
            request_id=_request_id(request),
        )
    except FacadeError as exc:
        return _facade_error_response(exc)
    if request_body.stream:
        return StreamingResponse(
            _response_sse(response), media_type="text/event-stream"
        )
    return response
