from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    import boto3  # type: ignore
    from botocore.config import Config as BotocoreConfig  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore
    BotocoreConfig = None  # type: ignore


BedrockClientFactory = Callable[..., Any]
BedrockSessionFactory = Callable[..., Any]
BedrockConfigFactory = Callable[..., Any]
BEDROCK_MANTLE_MIN_MAX_OUTPUT_TOKENS = 16
_SAFE_PROVIDER_ERROR_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_PROVIDER_ERROR_PARAM = re.compile(r"^[A-Za-z0-9_.:\[\]/-]{1,160}$")


@dataclass(frozen=True, repr=False)
class BedrockCredentials:
    """Ephemeral AWS credentials resolved through an approved Norman Keys broker."""

    access_key_id: str
    secret_access_key: str
    session_token: str = ""
    source: str = ""
    secret_name: str = ""
    lease_id: str = ""
    request_id: str = ""
    expires_at: str = ""

    def receipt_metadata(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "source": self.source,
                "secret_name": self.secret_name,
                "lease_id": self.lease_id,
                "request_id": self.request_id,
                "expires_at": self.expires_at,
            }.items()
            if value
        }


@dataclass(frozen=True, repr=False)
class BedrockMantleApiKey:
    """Opaque Bedrock Mantle API key resolved through Norman Keys."""

    api_key: str
    source: str = ""
    secret_name: str = ""
    lease_id: str = ""
    request_id: str = ""
    expires_at: str = ""

    def receipt_metadata(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "source": self.source,
                "secret_name": self.secret_name,
                "lease_id": self.lease_id,
                "request_id": self.request_id,
                "expires_at": self.expires_at,
            }.items()
            if value
        }


class BedrockMantleResponsesError(RuntimeError):
    """A Mantle failure with strictly sanitized provider metadata."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int = 0,
        provider_error_type: str = "",
        provider_error_code: str = "",
        provider_error_param: str = "",
    ) -> None:
        super().__init__(message)
        self.http_status = _nonnegative_int(http_status)
        self.provider_error_type = provider_error_type
        self.provider_error_code = provider_error_code
        self.provider_error_param = provider_error_param

    def safe_metadata(self) -> dict[str, int | str]:
        return {
            key: value
            for key, value in {
                "http_status": self.http_status,
                "provider_error_type": self.provider_error_type,
                "provider_error_code": self.provider_error_code,
                "provider_error_param": self.provider_error_param,
            }.items()
            if value
        }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_provider_error_identifier(value: Any) -> str:
    candidate = _clean(value)
    if _SAFE_PROVIDER_ERROR_IDENTIFIER.fullmatch(candidate):
        return candidate
    return ""


def _safe_provider_error_param(value: Any) -> str:
    """Keep only a schema-field pointer, never provider-supplied values or prose."""

    candidate = _clean(value)
    if _SAFE_PROVIDER_ERROR_PARAM.fullmatch(candidate):
        return candidate
    return ""


def _mantle_http_error_metadata(
    error: urllib_error.HTTPError,
) -> tuple[str, str, str]:
    """Read only allowlisted error identifiers and a schema pointer."""

    try:
        body = error.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "", "", ""
    if not isinstance(parsed, Mapping):
        return "", "", ""
    details = parsed.get("error")
    details = details if isinstance(details, Mapping) else parsed
    return (
        _safe_provider_error_identifier(details.get("type")),
        _safe_provider_error_identifier(details.get("code")),
        _safe_provider_error_param(details.get("param")),
    )


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean(os.getenv(name))
        if value:
            return value
    return ""


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timeout_seconds(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 0.0
    return timeout if timeout > 0 else 0.0


def _bedrock_client_config(
    timeout_seconds: float,
    *,
    config_factory: BedrockConfigFactory | None = None,
) -> Any | None:
    timeout = _timeout_seconds(timeout_seconds)
    if not timeout:
        return None
    factory = config_factory or BotocoreConfig
    if factory is None:  # pragma: no cover - boto3 includes botocore
        return None
    return factory(
        connect_timeout=min(timeout, 10.0),
        read_timeout=timeout,
        retries={"mode": "standard", "total_max_attempts": 1},
    )


def bedrock_region(route_policy: Mapping[str, Any] | None = None) -> str:
    policy = route_policy or {}
    return (
        _clean(policy.get("aws_region"))
        or _clean(policy.get("region"))
        or _clean(os.getenv("AWS_REGION"))
        or _clean(os.getenv("AWS_DEFAULT_REGION"))
    )


def bedrock_profile(route_policy: Mapping[str, Any] | None = None) -> str:
    policy = route_policy or {}
    return _clean(policy.get("aws_profile")) or _clean(policy.get("profile"))


def bedrock_credentials_secret(
    route_policy: Mapping[str, Any] | None = None,
) -> str:
    policy = route_policy or {}
    return (
        _clean(policy.get("aws_credentials_secret"))
        or _clean(policy.get("aws_credentials_secret_name"))
        or _clean(policy.get("bedrock_credentials_secret"))
    )


def bedrock_mantle_api_key_secret(
    route_policy: Mapping[str, Any] | None = None,
) -> str:
    policy = route_policy or {}
    return _clean(policy.get("bedrock_mantle_api_key_secret")) or _clean(
        policy.get("bedrock_mantle_api_key_secret_name")
    )


def _keys_secret_get_url() -> str:
    base = _first_env("NORMAN_KEYS_URL", "NORMAN_KEYS_API_BASE").rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/secrets/get"):
        return base
    if base.endswith("/v1"):
        return f"{base}/secrets/get"
    return f"{base}/v1/secrets/get"


def _keys_timeout_seconds(timeout_seconds: float = 0) -> float:
    configured = _timeout_seconds(os.getenv("NORMAN_KEYS_TIMEOUT_SECONDS"))
    timeout = configured or 2.0
    invocation_timeout = _timeout_seconds(timeout_seconds)
    if invocation_timeout:
        timeout = min(timeout, invocation_timeout)
    return max(0.1, timeout)


def _command_from_config(configured: str, secret_name: str) -> list[str]:
    if not configured:
        return []
    command = shlex.split(configured)
    if not command:
        return []
    if "{name}" in configured:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _secret_command(secret_name: str) -> list[str]:
    return _command_from_config(
        _first_env("NORMAN_SECRET_CMD", "NORMAN_CONFIG_SECRET_CMD"),
        secret_name,
    )


def _bedrock_mantle_secret_command(secret_name: str) -> list[str]:
    """Resolve only the dedicated Mantle token broker command, when configured."""

    return _command_from_config(
        _first_env("NORMAN_BEDROCK_MANTLE_SECRET_CMD"),
        secret_name,
    )


def _broker_secret_from_http(
    secret_name: str,
    *,
    requester_id: str,
    session_id: str,
    lane: str,
    target_host: str,
    timeout_seconds: float,
    reason: str = "Native Bedrock runtime credentials",
) -> tuple[str, dict[str, str]]:
    url = _keys_secret_get_url()
    if not url:
        raise RuntimeError("Norman Keys HTTP broker is not configured")
    payload = {
        "name": secret_name,
        "reason": reason,
        "requester_id": requester_id,
        "session_id": session_id,
        "lane": lane,
        "target_host": target_host,
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = _first_env("NORMAN_KEYS_TOKEN", "NORMAN_KEYS_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib_request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body) if body else {}
    if not isinstance(parsed, Mapping):
        raise ValueError("Norman Keys returned an invalid credential response")
    value = _clean(parsed.get("value") or parsed.get("secret"))
    if not value:
        raise ValueError("Norman Keys returned an empty credential response")
    return value, {
        key: _clean(parsed.get(key))
        for key in ("lease_id", "request_id", "expires_at")
        if _clean(parsed.get(key))
    }


def _broker_secret_from_command(
    secret_name: str,
    *,
    timeout_seconds: float,
    command: Sequence[str] | None = None,
) -> tuple[str, dict[str, str]]:
    resolved_command = (
        list(command) if command is not None else _secret_command(secret_name)
    )
    if not resolved_command:
        raise RuntimeError("Norman Keys broker command is not configured")
    result = subprocess.run(
        resolved_command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    value = _clean(result.stdout)
    if not value:
        raise ValueError("Norman Keys broker command returned an empty credential")
    return value, {}


def _credential_value(bundle: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(bundle.get(key))
        if value:
            return value
    return ""


def _parse_brokered_credentials(
    raw_value: str,
    *,
    source: str,
    secret_name: str,
    lease_metadata: Mapping[str, str],
) -> BedrockCredentials:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("AWS credential bundle must be a JSON object") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("AWS credential bundle must be a JSON object")
    bundle = parsed.get("credentials")
    if not isinstance(bundle, Mapping):
        bundle = parsed
    access_key_id = _credential_value(
        bundle,
        "aws_access_key_id",
        "access_key_id",
        "AWS_ACCESS_KEY_ID",
        "AccessKeyId",
    )
    secret_access_key = _credential_value(
        bundle,
        "aws_secret_access_key",
        "secret_access_key",
        "AWS_SECRET_ACCESS_KEY",
        "SecretAccessKey",
    )
    session_token = _credential_value(
        bundle,
        "aws_session_token",
        "session_token",
        "AWS_SESSION_TOKEN",
        "SessionToken",
    )
    if not access_key_id or not secret_access_key:
        raise ValueError("AWS credential bundle is missing required fields")
    return BedrockCredentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
        source=source,
        secret_name=secret_name,
        lease_id=_clean(lease_metadata.get("lease_id")),
        request_id=_clean(lease_metadata.get("request_id")),
        expires_at=_clean(lease_metadata.get("expires_at")),
    )


def _credential_request_context(
    policy: Mapping[str, Any],
    *,
    requester_id: str,
    session_id: str,
    lane: str,
    target_host: str,
) -> dict[str, str]:
    return {
        "requester_id": (
            _clean(policy.get("aws_credentials_requester_id"))
            or _clean(policy.get("bedrock_credentials_requester_id"))
            or _clean(requester_id)
            or "console-runtime-bedrock"
        ),
        "session_id": (
            _clean(policy.get("aws_credentials_session_id"))
            or _clean(policy.get("bedrock_credentials_session_id"))
            or _clean(session_id)
        ),
        "lane": (
            _clean(policy.get("aws_credentials_lane"))
            or _clean(policy.get("bedrock_credentials_lane"))
            or _clean(lane)
        ),
        "target_host": (
            _clean(policy.get("aws_credentials_target_host"))
            or _clean(policy.get("bedrock_credentials_target_host"))
            or _clean(target_host)
            or socket.gethostname()
        ),
    }


def _credentials_from_http(
    secret_name: str,
    *,
    context: Mapping[str, str],
    timeout_seconds: float,
) -> BedrockCredentials:
    raw_value, metadata = _broker_secret_from_http(
        secret_name,
        requester_id=context["requester_id"],
        session_id=context["session_id"],
        lane=context["lane"],
        target_host=context["target_host"],
        timeout_seconds=timeout_seconds,
    )
    return _parse_brokered_credentials(
        raw_value,
        source="norman_keys",
        secret_name=secret_name,
        lease_metadata=metadata,
    )


def _credentials_from_command(
    secret_name: str, *, timeout_seconds: float
) -> BedrockCredentials:
    raw_value, metadata = _broker_secret_from_command(
        secret_name,
        timeout_seconds=timeout_seconds,
    )
    return _parse_brokered_credentials(
        raw_value,
        source="secret_command",
        secret_name=secret_name,
        lease_metadata=metadata,
    )


def resolve_bedrock_credentials(
    route_policy: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float = 0,
    requester_id: str = "",
    session_id: str = "",
    lane: str = "",
    target_host: str = "",
) -> BedrockCredentials | None:
    """Resolve explicitly configured Bedrock credentials through Norman Keys."""

    policy = route_policy or {}
    secret_name = bedrock_credentials_secret(policy)
    if not secret_name:
        return None
    context = _credential_request_context(
        policy,
        requester_id=requester_id,
        session_id=session_id,
        lane=lane,
        target_host=target_host,
    )
    broker_timeout = _keys_timeout_seconds(timeout_seconds)
    failures = 0
    if _keys_secret_get_url():
        try:
            return _credentials_from_http(
                secret_name,
                context=context,
                timeout_seconds=broker_timeout,
            )
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib_error.URLError,
            ValueError,
        ):
            failures += 1
    if _secret_command(secret_name):
        try:
            return _credentials_from_command(
                secret_name,
                timeout_seconds=broker_timeout,
            )
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
            ValueError,
        ):
            failures += 1
    if not failures:
        raise RuntimeError(
            "Bedrock brokered credentials require NORMAN_KEYS_URL or NORMAN_SECRET_CMD"
        )
    raise RuntimeError("Bedrock brokered credential lookup failed")


def resolve_bedrock_mantle_api_key(
    route_policy: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float = 0,
    requester_id: str = "",
    session_id: str = "",
    lane: str = "",
    target_host: str = "",
) -> BedrockMantleApiKey:
    """Resolve an explicit Bedrock Mantle API key through Norman Keys."""

    policy = route_policy or {}
    secret_name = bedrock_mantle_api_key_secret(policy)
    if not secret_name:
        raise RuntimeError("Bedrock Mantle API key alias is not configured")
    context = _credential_request_context(
        policy,
        requester_id=requester_id,
        session_id=session_id,
        lane=lane,
        target_host=target_host,
    )
    broker_timeout = _keys_timeout_seconds(timeout_seconds)
    failures = 0
    dedicated_command = _bedrock_mantle_secret_command(secret_name)
    if dedicated_command:
        try:
            raw_value, metadata = _broker_secret_from_command(
                secret_name,
                timeout_seconds=broker_timeout,
                command=dedicated_command,
            )
            return BedrockMantleApiKey(
                api_key=raw_value,
                source="bedrock_mantle_secret_command",
                secret_name=secret_name,
                lease_id=_clean(metadata.get("lease_id")),
                request_id=_clean(metadata.get("request_id")),
                expires_at=_clean(metadata.get("expires_at")),
            )
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
            ValueError,
        ):
            failures += 1
    if _keys_secret_get_url():
        try:
            raw_value, metadata = _broker_secret_from_http(
                secret_name,
                requester_id=context["requester_id"],
                session_id=context["session_id"],
                lane=context["lane"],
                target_host=context["target_host"],
                timeout_seconds=broker_timeout,
                reason="Bedrock Mantle Responses API key",
            )
            return BedrockMantleApiKey(
                api_key=raw_value,
                source="norman_keys",
                secret_name=secret_name,
                lease_id=_clean(metadata.get("lease_id")),
                request_id=_clean(metadata.get("request_id")),
                expires_at=_clean(metadata.get("expires_at")),
            )
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib_error.URLError,
            ValueError,
        ):
            failures += 1
    if _secret_command(secret_name):
        try:
            raw_value, metadata = _broker_secret_from_command(
                secret_name,
                timeout_seconds=broker_timeout,
            )
            return BedrockMantleApiKey(
                api_key=raw_value,
                source="secret_command",
                secret_name=secret_name,
                lease_id=_clean(metadata.get("lease_id")),
                request_id=_clean(metadata.get("request_id")),
                expires_at=_clean(metadata.get("expires_at")),
            )
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
            ValueError,
        ):
            failures += 1
    if not failures:
        raise RuntimeError(
            "Bedrock Mantle API key requires NORMAN_BEDROCK_MANTLE_SECRET_CMD, "
            "NORMAN_KEYS_URL, or NORMAN_SECRET_CMD"
        )
    raise RuntimeError("Bedrock Mantle API key lookup failed")


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return _clean(value)
    parts: list[str] = []
    for part in value:
        if isinstance(part, str):
            text = part.strip()
        elif isinstance(part, Mapping):
            text = _clean(part.get("text") or part.get("content"))
        else:
            text = _clean(part)
        if text:
            parts.append(text)
    return "\n".join(parts)


def bedrock_messages(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    system: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, list[dict[str, str]]]]]:
    """Convert generic chat messages to Bedrock Converse content blocks."""

    system_texts = [_clean(system)] if _clean(system) else []
    converted: list[dict[str, list[dict[str, str]]]] = []
    for message in messages or []:
        role = _clean(message.get("role")).lower()
        text = _content_text(message.get("content"))
        if not text:
            continue
        if role in {"system", "developer"}:
            system_texts.append(text)
            continue
        bedrock_role = "assistant" if role == "assistant" else "user"
        content = {"text": text}
        if converted and converted[-1]["role"] == bedrock_role:
            converted[-1]["content"].append(content)
        else:
            converted.append({"role": bedrock_role, "content": [content]})
    if not converted:
        raise ValueError("Bedrock Converse requires at least one chat message")
    return (
        [{"text": text} for text in system_texts if text],
        converted,
    )


def build_bedrock_converse_request(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]] | None,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> dict[str, Any]:
    clean_model = _clean(model)
    if not clean_model:
        raise ValueError("Bedrock Converse route is missing a model")
    system_blocks, converse_messages = bedrock_messages(messages, system=system)
    inference_config: dict[str, Any] = {
        "maxTokens": _positive_int(max_tokens, 1024),
        "temperature": _number(temperature, 0.0),
    }
    payload: dict[str, Any] = {
        "modelId": clean_model,
        "messages": converse_messages,
        "inferenceConfig": inference_config,
    }
    if system_blocks:
        payload["system"] = system_blocks
    return payload


def _client_kwargs(region: str, config: Any | None) -> dict[str, Any]:
    kwargs = {"region_name": region} if region else {}
    if config is not None:
        kwargs["config"] = config
    return kwargs


def _session_factory_or_raise(
    session_factory: BedrockSessionFactory | None,
) -> BedrockSessionFactory:
    if session_factory is not None:
        return session_factory
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; Bedrock runtime is unavailable")
    return boto3.Session


def _credential_session_kwargs(
    credentials: BedrockCredentials,
    region: str,
) -> dict[str, str]:
    kwargs = {
        "aws_access_key_id": credentials.access_key_id,
        "aws_secret_access_key": credentials.secret_access_key,
    }
    if credentials.session_token:
        kwargs["aws_session_token"] = credentials.session_token
    if region:
        kwargs["region_name"] = region
    return kwargs


def _profile_session_kwargs(profile: str, region: str) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    if profile:
        kwargs["profile_name"] = profile
    if region:
        kwargs["region_name"] = region
    return kwargs


def _session_client(
    session_factory: BedrockSessionFactory | None,
    *,
    session_kwargs: Mapping[str, str],
    client_kwargs: Mapping[str, Any],
) -> Any:
    session = _session_factory_or_raise(session_factory)(**session_kwargs)
    return session.client("bedrock-runtime", **client_kwargs)


def create_bedrock_runtime_client(
    *,
    region: str = "",
    profile: str = "",
    credentials: BedrockCredentials | None = None,
    timeout_seconds: float = 0,
    client_factory: BedrockClientFactory | None = None,
    session_factory: BedrockSessionFactory | None = None,
    config_factory: BedrockConfigFactory | None = None,
) -> Any:
    clean_region = _clean(region)
    clean_profile = _clean(profile)
    client_config = _bedrock_client_config(
        timeout_seconds,
        config_factory=config_factory,
    )
    if client_factory is not None:
        kwargs: dict[str, Any] = {"service_name": "bedrock-runtime"}
        if clean_region:
            kwargs["region_name"] = clean_region
        if credentials is not None:
            kwargs["aws_access_key_id"] = credentials.access_key_id
            kwargs["aws_secret_access_key"] = credentials.secret_access_key
            if credentials.session_token:
                kwargs["aws_session_token"] = credentials.session_token
        elif clean_profile:
            kwargs["profile_name"] = clean_profile
        if client_config is not None:
            kwargs["config"] = client_config
        return client_factory(**kwargs)
    client_kwargs = _client_kwargs(clean_region, client_config)
    if credentials is not None:
        return _session_client(
            session_factory,
            session_kwargs=_credential_session_kwargs(credentials, clean_region),
            client_kwargs=client_kwargs,
        )
    if clean_profile or session_factory is not None:
        return _session_client(
            session_factory,
            session_kwargs=_profile_session_kwargs(clean_profile, clean_region),
            client_kwargs=client_kwargs,
        )
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; Bedrock runtime is unavailable")
    return boto3.client("bedrock-runtime", **client_kwargs)


def invoke_bedrock_converse(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]] | None,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float | None = None,
    region: str = "",
    profile: str = "",
    credentials: BedrockCredentials | None = None,
    timeout_seconds: float = 0,
    client_factory: BedrockClientFactory | None = None,
    session_factory: BedrockSessionFactory | None = None,
    config_factory: BedrockConfigFactory | None = None,
) -> dict[str, Any]:
    client = create_bedrock_runtime_client(
        region=region,
        profile=profile,
        credentials=credentials,
        timeout_seconds=timeout_seconds,
        client_factory=client_factory,
        session_factory=session_factory,
        config_factory=config_factory,
    )
    payload = build_bedrock_converse_request(
        model=model,
        messages=messages,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    response = client.converse(**payload)
    if not isinstance(response, dict):
        raise RuntimeError("Bedrock Converse returned a non-object response")
    return response


def normalize_bedrock_converse_response(response: Mapping[str, Any]) -> dict[str, Any]:
    output = response.get("output")
    message = output.get("message") if isinstance(output, Mapping) else {}
    content = message.get("content") if isinstance(message, Mapping) else []
    text_parts = [
        _clean(part.get("text"))
        for part in content
        if isinstance(part, Mapping) and _clean(part.get("text"))
    ]
    usage = response.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    input_tokens = _nonnegative_int(usage.get("inputTokens"))
    output_tokens = _nonnegative_int(usage.get("outputTokens"))
    total_tokens = max(
        _nonnegative_int(
            usage.get("totalTokens"),
            input_tokens + output_tokens,
        ),
        input_tokens + output_tokens,
    )
    return {
        "text": "\n".join(text_parts),
        "stop_reason": _clean(response.get("stopReason")) or "stop",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
    }


def bedrock_mantle_responses_url(region: str) -> str:
    clean_region = _clean(region)
    if not clean_region:
        raise ValueError("Bedrock Mantle route is missing an AWS region")
    return f"https://bedrock-mantle.{clean_region}.api.aws/openai/v1/responses"


def bedrock_mantle_responses_input(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    system: str = "",
) -> list[dict[str, Any]]:
    """Convert generic chat messages to the OpenAI-compatible Responses input."""

    converted: list[dict[str, Any]] = []
    if _clean(system):
        converted.append(
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": _clean(system)}],
            }
        )
    for message in messages or []:
        item_type = _clean(message.get("type")).lower()
        if item_type == "function_call":
            call_id = _clean(message.get("call_id"))
            name = _clean(message.get("name"))
            if not call_id or not name:
                raise ValueError(
                    "Bedrock Mantle function_call input requires call_id and name"
                )
            arguments = message.get("arguments", "")
            if isinstance(arguments, (Mapping, list)):
                arguments = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
            function_call = {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": str(arguments or ""),
            }
            for field in ("id", "status"):
                value = message.get(field)
                if isinstance(value, str) and value:
                    function_call[field] = value
            converted.append(function_call)
            continue
        if item_type == "function_call_output":
            call_id = _clean(message.get("call_id"))
            if not call_id:
                raise ValueError(
                    "Bedrock Mantle function_call_output input requires call_id"
                )
            output = message.get("output", "")
            if isinstance(output, (Mapping, list)):
                output = json.dumps(output, sort_keys=True, separators=(",", ":"))
            converted.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": str(output or ""),
                }
            )
            continue
        if item_type == "reasoning":
            # Reasoning-model function continuations must replay the provider's
            # native reasoning item unchanged alongside the function result.
            converted.append(dict(message))
            continue
        if item_type == "message" and _clean(message.get("role")).lower() in {
            "",
            "assistant",
        }:
            # Preserve native assistant output instead of flattening it into a
            # generic chat message. This keeps provider item identity intact.
            converted.append(dict(message))
            continue
        role = _clean(message.get("role")).lower()
        text = _content_text(message.get("content"))
        if not text:
            continue
        if role in {"system", "developer"}:
            mantle_role = "developer"
            content_type = "input_text"
        elif role == "assistant":
            mantle_role = "assistant"
            content_type = "output_text"
        elif role == "tool":
            mantle_role = "user"
            content_type = "input_text"
            text = f"Prior tool output (replayed context only): {text}"
        else:
            mantle_role = "user"
            content_type = "input_text"
        converted.append(
            {
                "role": mantle_role,
                "content": [{"type": content_type, "text": text}],
            }
        )
    if not converted:
        raise ValueError("Bedrock Mantle Responses requires at least one message")
    return converted


def _mantle_responses_options(
    responses_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Allow the native Responses fields supported by Bedrock Mantle."""

    options = responses_options or {}
    payload: dict[str, Any] = {}
    tools = options.get("tools")
    if isinstance(tools, list):
        payload["tools"] = [dict(tool) for tool in tools if isinstance(tool, Mapping)]
    tool_choice = options.get("tool_choice")
    if isinstance(tool_choice, (str, Mapping)):
        payload["tool_choice"] = (
            dict(tool_choice) if isinstance(tool_choice, Mapping) else tool_choice
        )
    if isinstance(options.get("parallel_tool_calls"), bool):
        payload["parallel_tool_calls"] = options["parallel_tool_calls"]
    for field in ("reasoning", "text"):
        value = options.get(field)
        if isinstance(value, Mapping):
            payload[field] = dict(value)
    include = options.get("include")
    if isinstance(include, list):
        payload["include"] = [str(value) for value in include if str(value).strip()]
    return payload


def build_bedrock_mantle_responses_request(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]] | None,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float | None = None,
    responses_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    clean_model = _clean(model)
    if not clean_model:
        raise ValueError("Bedrock Mantle route is missing a model")
    payload = {
        "model": clean_model,
        "input": bedrock_mantle_responses_input(messages, system=system),
        # Mantle currently rejects lower values and does not accept temperature.
        "max_output_tokens": max(
            BEDROCK_MANTLE_MIN_MAX_OUTPUT_TOKENS,
            _positive_int(max_tokens, 1024),
        ),
    }
    payload.update(_mantle_responses_options(responses_options))
    return payload


def invoke_bedrock_mantle_responses(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]] | None,
    api_key: BedrockMantleApiKey,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float | None = None,
    responses_options: Mapping[str, Any] | None = None,
    region: str = "",
    timeout_seconds: float = 0,
) -> dict[str, Any]:
    payload = build_bedrock_mantle_responses_request(
        model=model,
        messages=messages,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        responses_options=responses_options,
    )
    request = urllib_request.Request(
        bedrock_mantle_responses_url(region),
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(
            request,
            timeout=max(0.1, _timeout_seconds(timeout_seconds) or 45.0),
        ) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib_error.HTTPError as exc:
        (
            provider_error_type,
            provider_error_code,
            provider_error_param,
        ) = _mantle_http_error_metadata(exc)
        raise BedrockMantleResponsesError(
            f"Bedrock Mantle Responses request failed with HTTP {exc.code}",
            http_status=exc.code,
            provider_error_type=provider_error_type,
            provider_error_code=provider_error_code,
            provider_error_param=provider_error_param,
        ) from exc
    except (OSError, TimeoutError, urllib_error.URLError) as exc:
        raise RuntimeError("Bedrock Mantle Responses request failed") from exc
    try:
        parsed = json.loads(raw_response) if raw_response else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Bedrock Mantle Responses returned an invalid JSON response"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Bedrock Mantle Responses returned a non-object response")
    return parsed


def _mantle_response_text(response: Mapping[str, Any]) -> str:
    output_text = _clean(response.get("output_text"))
    if output_text:
        return output_text
    text_parts: list[str] = []
    output = response.get("output")
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes, bytearray)):
        return ""
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, Sequence) or isinstance(
            content, (str, bytes, bytearray)
        ):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            if isinstance(text, Mapping):
                text = text.get("value")
            clean_text = _clean(text)
            if clean_text:
                text_parts.append(clean_text)
    return "\n".join(text_parts)


def normalize_bedrock_mantle_responses(response: Mapping[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    input_tokens = _nonnegative_int(usage.get("input_tokens", usage.get("inputTokens")))
    output_tokens = _nonnegative_int(
        usage.get("output_tokens", usage.get("outputTokens"))
    )
    total_tokens = max(
        _nonnegative_int(usage.get("total_tokens", usage.get("totalTokens"))),
        input_tokens + output_tokens,
    )
    status = _clean(response.get("status")).lower()
    return {
        "text": _mantle_response_text(response),
        "stop_reason": "stop" if status in {"", "completed"} else status,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
    }
