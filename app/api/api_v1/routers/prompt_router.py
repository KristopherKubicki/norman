from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models import User
from app.services.prompt_load_balancer import (
    balance_prompt,
    prompt_load_balancer_capabilities,
    provider_adapter_decision,
)

router = APIRouter(prefix="/prompt-router", tags=["prompt_router"])


class PromptRouteRequest(BaseModel):
    prompt: str
    source: str = ""
    session: str = ""
    requested_runtime: str = "auto"
    requested_model: str = ""
    force_requested_runtime: bool = False
    allow_cloud_escalation: bool = True
    route_policy: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ProviderAdapterRequest(BaseModel):
    model: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    input: Any = None
    prompt: Any = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    norman: dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


@router.get("/capabilities")
async def prompt_router_capabilities(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return prompt_load_balancer_capabilities()


@router.post("/route")
async def route_prompt(
    request: PromptRouteRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return balance_prompt(
            prompt=request.prompt,
            source=request.source,
            session=request.session,
            requested_runtime=request.requested_runtime,
            requested_model=request.requested_model,
            force_requested_runtime=request.force_requested_runtime,
            allow_cloud_escalation=request.allow_cloud_escalation,
            route_policy=request.route_policy,
            context=request.context,
            artifacts=request.artifacts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/adapters/openai/chat/completions")
async def route_openai_chat_completion(
    request: ProviderAdapterRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return provider_adapter_decision(
            provider="openai",
            endpoint="openai.chat.completions",
            payload=request.dict(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/adapters/openai/responses")
async def route_openai_response(
    request: ProviderAdapterRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return provider_adapter_decision(
            provider="openai",
            endpoint="openai.responses",
            payload=request.dict(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
