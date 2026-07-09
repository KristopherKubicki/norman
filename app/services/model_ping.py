from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import anyio
import requests
from openai import OpenAI

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore

from app.core.config import settings
from app.services.norllama.routing import NORLLAMA_PROVIDER_ALIASES

PING_PROMPT = "Reply exactly: NORMAN-MODEL-PING"
EXPECTED_PING_TEXT = "NORMAN-MODEL-PING"


@dataclass(frozen=True)
class ModelPingTarget:
    id: str
    name: str
    provider: str
    model: str
    slot: str = "custom"
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    region: str = ""
    max_tokens: int = 16
    timeout_seconds: float = 20.0

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("api_key", None)
        data["configured"] = _target_configured(self)
        data["base_url"] = _public_endpoint(self.base_url)
        return data


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "model"


def _public_endpoint(value: str) -> str:
    raw = _clean_str(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.split("?", 1)[0]
    if not parsed.netloc:
        return raw.split("?", 1)[0]
    netloc = parsed.hostname or parsed.netloc.rsplit("@", 1)[-1]
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _target_api_key(target: ModelPingTarget) -> str:
    if target.api_key_env:
        return _clean_str(os.getenv(target.api_key_env))
    return _clean_str(target.api_key)


def _target_configured(target: ModelPingTarget) -> bool:
    provider = target.provider.lower()
    if provider == "bedrock":
        return True
    if provider in NORLLAMA_PROVIDER_ALIASES:
        return bool(target.base_url)
    if provider == "openai_compatible":
        return bool(target.base_url)
    if provider == "openai":
        return bool(
            _target_api_key(target)
            or _clean_str(getattr(settings, "openai_api_key", ""))
        )
    return bool(_target_api_key(target))


def _configured_timeout() -> float:
    value = getattr(settings, "llm_provider_timeout_seconds", 20)
    try:
        return max(1.0, min(float(value), 120.0))
    except (TypeError, ValueError):
        return 20.0


def _provider_chain_targets() -> list[ModelPingTarget]:
    timeout = _configured_timeout()
    default_model = _clean_str(getattr(settings, "openai_default_model", ""))
    primary_kind = (
        _clean_str(getattr(settings, "llm_primary_provider", "openai")).lower()
        or "openai"
    )
    primary_model = (
        _clean_str(getattr(settings, "llm_primary_model", "")) or default_model
    )
    primary_key = _clean_str(
        getattr(settings, "llm_primary_api_key", "")
    ) or _clean_str(getattr(settings, "openai_api_key", ""))
    primary_base_url = _clean_str(getattr(settings, "llm_primary_base_url", ""))

    targets: list[ModelPingTarget] = []
    if primary_kind == "openai" and primary_key and primary_model:
        targets.append(
            ModelPingTarget(
                id="provider-primary",
                name="Primary OpenAI",
                provider="openai",
                model=primary_model,
                slot="primary",
                api_key=primary_key,
                base_url=primary_base_url,
                timeout_seconds=timeout,
            )
        )
    elif primary_kind != "disabled" and primary_base_url and primary_model:
        targets.append(
            ModelPingTarget(
                id="provider-primary",
                name="Primary",
                provider=primary_kind,
                model=primary_model,
                slot="primary",
                api_key=_clean_str(getattr(settings, "llm_primary_api_key", "")),
                base_url=primary_base_url,
                timeout_seconds=timeout,
            )
        )

    for slot, label in (("backup", "Backup"), ("offline", "Offline")):
        kind = _clean_str(getattr(settings, f"llm_{slot}_provider", "disabled")).lower()
        base_url = _clean_str(getattr(settings, f"llm_{slot}_base_url", ""))
        model = _clean_str(getattr(settings, f"llm_{slot}_model", "")) or default_model
        if kind and kind != "disabled" and base_url and model:
            targets.append(
                ModelPingTarget(
                    id=f"provider-{slot}",
                    name=label,
                    provider=kind,
                    model=model,
                    slot=slot,
                    api_key=_clean_str(getattr(settings, f"llm_{slot}_api_key", "")),
                    base_url=base_url,
                    timeout_seconds=timeout,
                )
            )
    return targets


def _custom_targets() -> list[ModelPingTarget]:
    raw_targets = getattr(settings, "llm_ping_targets", []) or []
    if not isinstance(raw_targets, list):
        return []
    targets: list[ModelPingTarget] = []
    default_timeout = _configured_timeout()
    for index, item in enumerate(raw_targets, start=1):
        if not isinstance(item, dict):
            continue
        provider = _clean_str(item.get("provider")).lower() or "openai_compatible"
        model = _clean_str(item.get("model"))
        name = _clean_str(item.get("name")) or model or f"Model {index}"
        if not model:
            continue
        target_id = _clean_str(item.get("id")) or f"target-{_slug(name)}"
        try:
            timeout = float(item.get("timeout_seconds") or default_timeout)
        except (TypeError, ValueError):
            timeout = default_timeout
        try:
            max_tokens = int(item.get("max_tokens") or 16)
        except (TypeError, ValueError):
            max_tokens = 16
        targets.append(
            ModelPingTarget(
                id=target_id,
                name=name,
                provider=provider,
                model=model,
                slot=_clean_str(item.get("slot")) or "custom",
                base_url=_clean_str(item.get("base_url")),
                api_key=_clean_str(item.get("api_key")),
                api_key_env=_clean_str(item.get("api_key_env")),
                region=_clean_str(item.get("region")),
                max_tokens=max(1, min(max_tokens, 128)),
                timeout_seconds=max(1.0, min(timeout, 120.0)),
            )
        )
    return targets


def list_model_ping_targets() -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for target in [*_provider_chain_targets(), *_custom_targets()]:
        if target.id in seen:
            continue
        seen.add(target.id)
        result.append(target.public_dict())
    return result


def _all_targets() -> list[ModelPingTarget]:
    seen: set[str] = set()
    targets: list[ModelPingTarget] = []
    for target in [*_provider_chain_targets(), *_custom_targets()]:
        if target.id in seen:
            continue
        seen.add(target.id)
        targets.append(target)
    return targets


def _openai_client(target: ModelPingTarget) -> OpenAI:
    api_key = _target_api_key(target)
    if not api_key and target.provider == "openai":
        api_key = _clean_str(getattr(settings, "openai_api_key", ""))
    if not api_key and target.provider == "openai":
        raise RuntimeError("OpenAI target is missing api_key or api_key_env")
    if not api_key and target.provider == "openai_compatible":
        api_key = "local"
    kwargs: dict[str, Any] = {
        "api_key": api_key or "local",
        "timeout": target.timeout_seconds,
    }
    if target.base_url:
        kwargs["base_url"] = target.base_url
    return OpenAI(**kwargs)


def _ping_openai_chat(target: ModelPingTarget) -> str:
    response = _openai_client(target).chat.completions.create(
        model=target.model,
        messages=[{"role": "user", "content": PING_PROMPT}],
        max_tokens=target.max_tokens,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return _clean_str(getattr(message, "content", ""))


def _ping_anthropic(target: ModelPingTarget) -> str:
    api_key = _target_api_key(target)
    if not api_key:
        raise RuntimeError("Anthropic target is missing api_key or api_key_env")
    base_url = target.base_url or "https://api.anthropic.com"
    url = f"{base_url.rstrip('/')}/v1/messages"
    response = requests.post(
        url,
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        json={
            "model": target.model,
            "max_tokens": target.max_tokens,
            "messages": [{"role": "user", "content": PING_PROMPT}],
        },
        timeout=target.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    parts = payload.get("content") or []
    texts = [
        _clean_str(part.get("text"))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(text for text in texts if text)


def _ping_bedrock(target: ModelPingTarget) -> str:
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; Bedrock ping is unavailable")
    region = target.region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    kwargs = {"region_name": region} if region else {}
    client = boto3.client("bedrock-runtime", **kwargs)
    response = client.converse(
        modelId=target.model,
        messages=[{"role": "user", "content": [{"text": PING_PROMPT}]}],
        inferenceConfig={"maxTokens": target.max_tokens, "temperature": 0},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    texts = [
        _clean_str(part.get("text"))
        for part in content
        if isinstance(part, dict) and part.get("text")
    ]
    return "\n".join(text for text in texts if text)


def _ping_norllama(target: ModelPingTarget) -> str:
    headers = {"content-type": "application/json"}
    api_key = _target_api_key(target)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    response = requests.post(
        f"{target.base_url.rstrip('/')}/api/generate",
        headers=headers,
        json={
            "model": target.model,
            "prompt": PING_PROMPT,
            "stream": False,
            "options": {"temperature": 0, "num_predict": target.max_tokens},
        },
        timeout=target.timeout_seconds,
    )
    response.raise_for_status()
    return _clean_str(response.json().get("response"))


def _ping_target_sync(target: ModelPingTarget) -> dict[str, Any]:
    started = time.perf_counter()
    provider = target.provider.lower()
    status = "ok"
    error = ""
    response_text = ""
    try:
        if provider in NORLLAMA_PROVIDER_ALIASES:
            response_text = _ping_norllama(target)
        elif provider in {"openai", "openai_compatible"}:
            response_text = _ping_openai_chat(target)
        elif provider == "anthropic":
            response_text = _ping_anthropic(target)
        elif provider == "bedrock":
            response_text = _ping_bedrock(target)
        else:
            raise RuntimeError(f"Unsupported model ping provider: {target.provider}")
        if EXPECTED_PING_TEXT not in response_text:
            status = "warn"
    except Exception as exc:
        status = "error"
        error = str(exc)
    latency_ms = int((time.perf_counter() - started) * 1000)
    result = target.public_dict()
    result.update(
        {
            "status": status,
            "latency_ms": latency_ms,
            "matched": EXPECTED_PING_TEXT in response_text,
            "response_preview": response_text[:160],
            "error": error[:240],
        }
    )
    return result


async def ping_model_targets(target_id: str = "") -> dict[str, Any]:
    targets = _all_targets()
    selected_id = _clean_str(target_id)
    if selected_id:
        targets = [target for target in targets if target.id == selected_id]
        if not targets:
            raise KeyError(selected_id)
    results = [
        await anyio.to_thread.run_sync(_ping_target_sync, target) for target in targets
    ]
    return {
        "checked_at": time.time(),
        "count": len(results),
        "ok": sum(1 for item in results if item["status"] == "ok"),
        "warn": sum(1 for item in results if item["status"] == "warn"),
        "error": sum(1 for item in results if item["status"] == "error"),
        "items": results,
    }
