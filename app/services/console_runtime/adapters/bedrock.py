from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from app.core.config import settings
from app.services.console_runtime.policy import resolve_runtime_mode
from app.services.console_runtime.types import (
    ModelCapabilities,
    ModelRequest,
    ModelResult,
    ModelUsage,
)
from app.services.norllama.bedrock import (
    BedrockClientFactory,
    BedrockConfigFactory,
    BedrockSessionFactory,
    bedrock_profile,
    bedrock_region,
    invoke_bedrock_converse,
    invoke_bedrock_mantle_responses,
    normalize_bedrock_converse_response,
    normalize_bedrock_mantle_responses,
    resolve_bedrock_credentials,
    resolve_bedrock_mantle_api_key,
)
from app.services.norllama.route_policy_artifact import (
    authorize_route_under_policy,
    policy_block_response,
)
from app.services.norllama.route_policy import (
    CLOUD_FALLBACK_BEDROCK_MODEL,
    cloud_fallback_allowed_for_alias,
    explicit_cloud_selection_for_model,
)
from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.types import (
    NorllamaRoute,
    NorllamaTaskKind,
    NorllamaTaskRequest,
)


BEDROCK_PROVIDERS = {"bedrock", "aws-bedrock"}
TASK_KIND_ALIASES = {
    "draft": "chat",
    "execute": "chat",
    "literal_response": "chat",
    "tool": "chat",
    "tools": "chat",
    "work": "chat",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "on", "enabled", "force"}


def _metadata_value(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(metadata.get(key))
        if value:
            return value
    return ""


def _task_kind_from_metadata(metadata: dict[str, Any]) -> NorllamaTaskKind:
    for key in (
        "norllama_task_kind",
        "goal_task_kind",
        "task_kind",
        "goal_phase",
        "phase",
    ):
        value = TASK_KIND_ALIASES.get(_clean(metadata.get(key)).lower(), "")
        if not value:
            value = _clean(metadata.get(key)).lower()
        if not value:
            continue
        try:
            return NorllamaTaskKind(value)
        except ValueError:
            continue
    return NorllamaTaskKind.CHAT


def _route_from_metadata(metadata: dict[str, Any]) -> NorllamaRoute | None:
    value = metadata.get("norllama_route")
    if not isinstance(value, dict):
        value = metadata.get("route")
    if not isinstance(value, dict):
        return None
    allowed = set(NorllamaRoute.__dataclass_fields__)
    payload = {key: value.get(key) for key in allowed if key in value}
    try:
        return NorllamaRoute(**payload)
    except TypeError:
        return None


def _route_policy(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("route_policy")
    return dict(value) if isinstance(value, dict) else {}


def _facade_cloud_fallback_allowed(
    metadata: dict[str, Any],
    route_policy: dict[str, Any],
    *,
    provider: str,
    model: str,
    lane: str,
) -> bool:
    """Accept only the narrow, signed fallback path owned by the facade."""

    marker = _mapping(metadata.get("norman_facade_cloud_fallback"))
    artifact = _mapping(route_policy.get("route_policy_artifact"))
    artifact_fallbacks = _mapping(artifact.get("fallbacks"))
    route_fallbacks = _mapping(route_policy.get("fallbacks"))
    try:
        attempt = int(marker.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    return bool(
        marker.get("schema") == "norman.facade-cloud-fallback.v1"
        and _clean(metadata.get("execution_mode"))
        == "prompt_intermediary_openai_facade_cloud_fallback"
        and attempt == 1
        and _clean(marker.get("requested_alias")).lower() == "norman-code"
        and _clean(marker.get("local_failure_code"))
        and _clean(provider).lower().replace("_", "-") == "aws-bedrock"
        and _clean(model) == CLOUD_FALLBACK_BEDROCK_MODEL
        and _clean(lane) == "coder"
        and artifact_fallbacks == route_fallbacks
        and cloud_fallback_allowed_for_alias(
            marker.get("requested_alias"),
            fallback_policy=artifact_fallbacks,
        )
        and _clean(artifact_fallbacks.get("cloud_fallback_provider")) == "aws-bedrock"
        and _clean(artifact_fallbacks.get("cloud_fallback_model"))
        == CLOUD_FALLBACK_BEDROCK_MODEL
        and _clean(artifact_fallbacks.get("cloud_fallback_lane")) == "coder"
    )


def _facade_explicit_cloud_selection_allowed(
    request: ModelRequest,
    route: NorllamaRoute,
    metadata: dict[str, Any],
    route_policy: dict[str, Any],
    *,
    provider: str,
    model: str,
    lane: str,
) -> bool:
    """Accept a facade-owned exact cloud selection only when policy agrees."""

    marker = _mapping(metadata.get("norman_facade_explicit_cloud_selection"))
    artifact = _mapping(route_policy.get("route_policy_artifact"))
    artifact_cloud_policy = _mapping(artifact.get("cloud_policy"))
    route_cloud_policy = _mapping(route_policy.get("cloud_policy"))
    requested_alias = _clean(marker.get("requested_alias")).lower()
    selection = explicit_cloud_selection_for_model(
        requested_alias,
        cloud_policy=artifact_cloud_policy,
    )
    if not selection:
        return False
    return bool(
        marker.get("schema") == "norman.facade-explicit-cloud-selection.v1"
        and _clean(metadata.get("execution_mode"))
        == "prompt_intermediary_openai_facade_explicit_cloud"
        and _clean(request.route_key).lower() == requested_alias
        and _clean(request.model) == selection["model"]
        and _clean(route.provider).lower().replace("_", "-") == selection["provider"]
        and _clean(route.model) == selection["model"]
        and _clean(route.lane).lower() == selection["lane"]
        and _clean(marker.get("provider")).lower().replace("_", "-")
        == selection["provider"]
        and _clean(marker.get("model")) == selection["model"]
        and _clean(marker.get("lane")).lower() == selection["lane"]
        and _clean(provider).lower().replace("_", "-") == selection["provider"]
        and _clean(model) == selection["model"]
        and _clean(lane).lower() == selection["lane"]
        and artifact_cloud_policy == route_cloud_policy
    )


def _route_policy_provider(route_policy: dict[str, Any]) -> str:
    for key in (
        "provider",
        "preferred_provider",
        "provider_surface",
        "model_proxy",
        "runtime",
    ):
        provider = _clean(route_policy.get(key)).lower().replace("_", "-")
        if provider:
            return provider
    return ""


def _deny_authorization(authorization: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **authorization,
        "allowed": False,
        "production_route_eligible": False,
        "reason": reason,
        "cloud_requested": True,
    }


def _temperature(request: ModelRequest, route_policy: dict[str, Any]) -> float:
    if request.temperature is not None:
        return float(request.temperature)
    try:
        return float(route_policy.get("temperature", 0))
    except (TypeError, ValueError):
        return 0.0


def _positive_float(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _model_timeout_seconds(request: ModelRequest) -> float:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    route_policy = _route_policy(metadata)
    explicit_timeout = 0.0
    for source in (route_policy, metadata):
        for key in (
            "model_timeout_seconds",
            "bedrock_timeout_seconds",
            "provider_timeout_seconds",
        ):
            explicit_timeout = _positive_float(source.get(key))
            if explicit_timeout:
                break
        if explicit_timeout:
            break
    default_timeout = _positive_float(
        getattr(settings, "console_runtime_bedrock_timeout_seconds", 0)
    ) or _positive_float(getattr(settings, "llm_provider_timeout_seconds", 0))
    timeout = explicit_timeout or default_timeout or 45.0
    budget_timeout = _positive_float(getattr(request.budget, "max_runtime_seconds", 0))
    if budget_timeout:
        timeout = min(timeout, budget_timeout)
    return max(1.0, timeout)


def _task_from_request(
    request: ModelRequest,
    metadata: dict[str, Any],
    route_policy: dict[str, Any],
) -> NorllamaTaskRequest:
    return NorllamaTaskRequest(
        kind=_task_kind_from_metadata(metadata),
        messages=request.messages,
        route_policy=route_policy,
        metadata=metadata,
        task_id=_metadata_value(metadata, "request_id", "invocation_id"),
    )


def _bedrock_route(
    task: NorllamaTaskRequest,
    metadata: dict[str, Any],
) -> tuple[NorllamaRoute, str]:
    route = _route_from_metadata(metadata) or route_task(task)
    provider = _clean(route.provider).lower().replace("_", "-")
    if (
        provider not in BEDROCK_PROVIDERS
        or not _flag(route.cloud_proxy)
        or _flag(route.local)
        or _flag(route.tool_lane)
    ):
        raise RuntimeError(
            "Bedrock adapter requires an explicit Bedrock cloud-proxy route"
        )
    return route, provider


def _route_authorization(
    route_policy: dict[str, Any],
    *,
    request: ModelRequest,
    route: NorllamaRoute,
    provider: str,
    model: str,
    lane: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    authorization = authorize_route_under_policy(
        policy_artifact=route_policy.get("route_policy_artifact")
        if isinstance(route_policy.get("route_policy_artifact"), dict)
        else None,
        execution_mode="bedrock_adapter",
        requested_provider=provider,
        requested_model=model,
        requested_lane=lane,
        manual_degraded_authorization=route_policy.get("manual_degraded_authorization")
        if isinstance(route_policy.get("manual_degraded_authorization"), dict)
        else None,
    )
    if _route_policy_provider(route_policy) not in BEDROCK_PROVIDERS:
        return _deny_authorization(
            authorization, "bedrock_route_not_selected_by_policy"
        )
    cloud_fallback = _facade_cloud_fallback_allowed(
        metadata,
        route_policy,
        provider=provider,
        model=model,
        lane=lane,
    )
    explicit_cloud_selection = _facade_explicit_cloud_selection_allowed(
        request,
        route,
        metadata,
        route_policy,
        provider=provider,
        model=model,
        lane=lane,
    )
    if (
        not _flag(route_policy.get("allow_cloud_proxy"))
        and not cloud_fallback
        and not explicit_cloud_selection
    ):
        return _deny_authorization(
            authorization, "bedrock_cloud_proxy_not_explicitly_allowed"
        )
    if not resolve_runtime_mode(route_policy).cloud_llm_allowed:
        return _deny_authorization(
            authorization, "bedrock_cloud_llm_disabled_by_policy"
        )
    return {
        **authorization,
        "cloud_fallback_authorized": cloud_fallback,
        "explicit_cloud_selection_authorized": explicit_cloud_selection,
    }


def _route_with_attribution(
    route: NorllamaRoute,
    *,
    authorization: dict[str, Any],
    credential_metadata: dict[str, str] | None = None,
) -> NorllamaRoute:
    attribution = {
        **route.attribution,
        "route_policy_authorization": authorization,
    }
    if credential_metadata:
        attribution["cloud_credentials"] = credential_metadata
    return replace(route, attribution=attribution)


def _credential_metadata(credentials: Any) -> dict[str, str]:
    return credentials.receipt_metadata() if credentials is not None else {}


def _uses_bedrock_mantle_responses(
    model: str,
    authorization: dict[str, Any],
) -> bool:
    """Use Mantle only for the explicit GPT selection authorized by the facade."""

    return bool(
        authorization.get("explicit_cloud_selection_authorized")
        and _clean(model).lower().startswith("openai.gpt-5.")
    )


def _request_credentials(
    route_policy: dict[str, Any],
    metadata: dict[str, Any],
    route: NorllamaRoute,
    timeout_seconds: float,
) -> Any:
    return resolve_bedrock_credentials(
        route_policy,
        timeout_seconds=timeout_seconds,
        requester_id=_metadata_value(
            metadata,
            "aws_credentials_requester_id",
            "bedrock_credentials_requester_id",
        ),
        session_id=_metadata_value(
            metadata,
            "console_runtime_job_id",
            "request_id",
            "invocation_id",
        ),
        lane=route.lane,
    )


def _request_mantle_api_key(
    route_policy: dict[str, Any],
    metadata: dict[str, Any],
    route: NorllamaRoute,
    timeout_seconds: float,
) -> Any:
    return resolve_bedrock_mantle_api_key(
        route_policy,
        timeout_seconds=timeout_seconds,
        requester_id=_metadata_value(
            metadata,
            "bedrock_mantle_api_key_requester_id",
            "aws_credentials_requester_id",
            "bedrock_credentials_requester_id",
        ),
        session_id=_metadata_value(
            metadata,
            "console_runtime_job_id",
            "request_id",
            "invocation_id",
        ),
        lane=route.lane,
    )


def _completion_output(
    *,
    metadata: dict[str, Any],
    model: str,
    route: NorllamaRoute,
    normalized: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    usage = normalized["usage"]
    return {
        "model": model,
        "text": normalized["text"],
        "stop_reason": normalized["stop_reason"],
        "usage": usage,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "route_selected_model": _metadata_value(metadata, "route_selected_model")
        or route.model,
        "requested_model": _metadata_value(metadata, "requested_model") or model,
        "target_model": model,
        "effective_runtime_model": model,
        "model_override_used": bool(metadata.get("model_override_used")),
        "model_override_reason": _metadata_value(metadata, "model_override_reason"),
        "invocation_id": _metadata_value(metadata, "invocation_id"),
        "raw": response,
    }


class BedrockModelAdapter:
    """Native AWS Bedrock Converse adapter for explicit cloud routes."""

    name = "bedrock"

    def __init__(
        self,
        *,
        client_factory: BedrockClientFactory | None = None,
        session_factory: BedrockSessionFactory | None = None,
        config_factory: BedrockConfigFactory | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._session_factory = session_factory
        self._config_factory = config_factory

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            provider=self.name,
            supports_tools=False,
            supports_streaming=False,
            supports_files=False,
            local=False,
            metadata={
                "transport": "aws_bedrock_converse",
                "native": True,
                "requires_explicit_cloud_route": True,
                "budget_timeout_enforced": True,
            },
        )

    def invoke(self, request: ModelRequest) -> ModelResult:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        route_policy = _route_policy(metadata)
        task = _task_from_request(request, metadata, route_policy)
        route, provider = _bedrock_route(task, metadata)
        model = (
            request.model or _metadata_value(metadata, "requested_model") or route.model
        )
        authorization = _route_authorization(
            route_policy,
            request=request,
            route=route,
            provider=provider,
            model=model,
            lane=route.lane,
            metadata=metadata,
        )
        if not authorization.get("allowed"):
            return self._policy_block_result(task, route, authorization)
        route = _route_with_attribution(route, authorization=authorization)
        return self._invoke_authorized(
            request,
            metadata=metadata,
            route_policy=route_policy,
            task=task,
            route=route,
            model=model,
            authorization=authorization,
        )

    def _invoke_authorized(
        self,
        request: ModelRequest,
        *,
        metadata: dict[str, Any],
        route_policy: dict[str, Any],
        task: NorllamaTaskRequest,
        route: NorllamaRoute,
        model: str,
        authorization: dict[str, Any],
    ) -> ModelResult:
        timeout_seconds = _model_timeout_seconds(request)
        if _uses_bedrock_mantle_responses(model, authorization):
            return self._invoke_mantle_authorized(
                request,
                metadata=metadata,
                route_policy=route_policy,
                task=task,
                route=route,
                model=model,
                authorization=authorization,
                timeout_seconds=timeout_seconds,
            )
        credentials = _request_credentials(
            route_policy,
            metadata,
            route,
            timeout_seconds,
        )
        credential_metadata = _credential_metadata(credentials)
        route = _route_with_attribution(
            route,
            authorization=authorization,
            credential_metadata=credential_metadata,
        )
        response = self._converse_response(
            request,
            route_policy=route_policy,
            model=model,
            credentials=credentials,
            timeout_seconds=timeout_seconds,
        )
        normalized = normalize_bedrock_converse_response(response)
        return self._completed_result(
            task=task,
            route=route,
            metadata=metadata,
            route_policy=route_policy,
            model=model,
            normalized=normalized,
            response=response,
            timeout_seconds=timeout_seconds,
            credential_metadata=credential_metadata,
            authorization=authorization,
        )

    def _invoke_mantle_authorized(
        self,
        request: ModelRequest,
        *,
        metadata: dict[str, Any],
        route_policy: dict[str, Any],
        task: NorllamaTaskRequest,
        route: NorllamaRoute,
        model: str,
        authorization: dict[str, Any],
        timeout_seconds: float,
    ) -> ModelResult:
        api_key = _request_mantle_api_key(
            route_policy,
            metadata,
            route,
            timeout_seconds,
        )
        api_key_metadata = _credential_metadata(api_key)
        route = _route_with_attribution(
            route,
            authorization=authorization,
            credential_metadata=api_key_metadata,
        )
        response = invoke_bedrock_mantle_responses(
            model=model,
            messages=request.messages,
            api_key=api_key,
            system=request.system,
            max_tokens=request.budget.max_output_tokens,
            temperature=_temperature(request, route_policy),
            region=bedrock_region(route_policy),
            timeout_seconds=timeout_seconds,
        )
        normalized = normalize_bedrock_mantle_responses(response)
        return self._completed_result(
            task=task,
            route=route,
            metadata=metadata,
            route_policy=route_policy,
            model=model,
            normalized=normalized,
            response=response,
            timeout_seconds=timeout_seconds,
            credential_metadata=api_key_metadata,
            credential_metadata_key="bedrock_mantle_api_key",
            transport="bedrock_mantle_responses",
            authorization=authorization,
        )

    def _converse_response(
        self,
        request: ModelRequest,
        *,
        route_policy: dict[str, Any],
        model: str,
        credentials: Any,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return invoke_bedrock_converse(
            model=model,
            messages=request.messages,
            system=request.system,
            max_tokens=request.budget.max_output_tokens,
            temperature=_temperature(request, route_policy),
            region=bedrock_region(route_policy),
            profile=bedrock_profile(route_policy),
            credentials=credentials,
            timeout_seconds=timeout_seconds,
            client_factory=self._client_factory,
            session_factory=self._session_factory,
            config_factory=self._config_factory,
        )

    def _completed_result(
        self,
        *,
        task: NorllamaTaskRequest,
        route: NorllamaRoute,
        metadata: dict[str, Any],
        route_policy: dict[str, Any],
        model: str,
        normalized: dict[str, Any],
        response: dict[str, Any],
        timeout_seconds: float,
        credential_metadata: dict[str, str],
        credential_metadata_key: str = "bedrock_credentials",
        transport: str = "aws_bedrock_converse",
        authorization: dict[str, Any],
    ) -> ModelResult:
        usage = normalized["usage"]
        receipt = build_task_receipt(
            task,
            route,
            status="completed",
            output=_completion_output(
                metadata=metadata,
                model=model,
                route=route,
                normalized=normalized,
                response=response,
            ),
        )
        return ModelResult(
            provider=self.name,
            model=model,
            text=normalized["text"],
            stop_reason=normalized["stop_reason"],
            usage=ModelUsage(**usage),
            metadata={
                "norllama_route": route.as_dict(),
                "norllama_receipt": receipt.as_dict(),
                "bedrock_region": bedrock_region(route_policy),
                "bedrock_profile": (
                    "" if credential_metadata else bedrock_profile(route_policy)
                ),
                "bedrock_timeout_seconds": timeout_seconds,
                "bedrock_transport": transport,
                credential_metadata_key: credential_metadata,
                "policy_authorization": authorization,
            },
            raw=response,
        )

    def _policy_block_result(
        self,
        task: NorllamaTaskRequest,
        route: NorllamaRoute,
        authorization: dict[str, Any],
    ) -> ModelResult:
        block = policy_block_response(authorization)
        route = replace(
            route,
            attribution={
                **route.attribution,
                "route_policy_authorization": authorization,
            },
        )
        receipt = build_task_receipt(
            task,
            route,
            status="blocked",
            output={
                "text": json.dumps(block, sort_keys=True),
                "output_shape": "error",
                "verifier_result": "fail",
            },
            error="route_policy_blocked",
        )
        return ModelResult(
            provider=self.name,
            model=route.model,
            text=json.dumps(block, sort_keys=True),
            stop_reason="policy_blocked",
            usage=ModelUsage(),
            metadata={
                "norllama_route": route.as_dict(),
                "norllama_receipt": receipt.as_dict(),
                "policy_authorization": authorization,
            },
            raw=block,
        )
