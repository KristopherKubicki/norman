from __future__ import annotations

import json
import os
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.prompt_load_balancer import prompt_load_balancer_capabilities
from app.services.prompt_provider_facade import (
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
    explicit = _clean(os.environ.get("NORMAN_PROMPT_PROXY_TOKEN"))
    if explicit:
        return explicit
    return _clean(settings.console_runtime_service_token)


def _bearer_token(request: Request) -> str:
    header = _clean(request.headers.get("authorization"))
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def _verify_proxy_token(request: Request) -> None:
    configured = _configured_proxy_token()
    if not configured:
        return
    if _bearer_token(request) != configured:
        raise HTTPException(
            status_code=401,
            detail="Could not validate Norman OpenAI-compatible proxy credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _request_id(request: Request) -> str:
    return (
        _clean(request.headers.get("x-request-id"))
        or _clean(request.headers.get("x-codex-request-id"))
        or _clean(request.headers.get("x-norman-request-id"))
    )


def _sse(lines: Iterable[dict[str, Any]]) -> Iterable[str]:
    for line in lines:
        yield f"data: {json.dumps(line, separators=(',', ':'))}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/v1/models")
async def openai_compat_models(request: Request) -> dict[str, Any]:
    _verify_proxy_token(request)
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
    _verify_proxy_token(request)
    try:
        response = execute_openai_chat_facade(
            request_body.dict(),
            request_id=_request_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
    _verify_proxy_token(request)
    try:
        response = execute_openai_responses_facade(
            request_body.dict(),
            request_id=_request_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if request_body.stream:
        return StreamingResponse(
            _response_sse(response), media_type="text/event-stream"
        )
    return response
