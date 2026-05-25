"""Runtime status for Norman's primary/backup/offline LLM lanes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from app.core.config import settings


DISABLED_PROVIDERS = {"", "disabled", "none", "off", "false"}
OLLAMA_PROVIDERS = {"ollama", "local_ollama", "local-ollama"}
OPENAI_COMPATIBLE_PROVIDERS = {
    "openai-compatible",
    "openai_compatible",
    "openai-compatible-local",
}
REQUEST_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProviderStatus:
    slot: str
    provider: str
    provider_label: str
    configured: bool
    available: bool
    model: str
    base_url: str
    mode: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "configured": self.configured,
            "available": self.available,
            "model": self.model,
            "base_url": self.base_url,
            "mode": self.mode,
            "reason": self.reason,
        }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _provider_label(provider: str) -> str:
    labels = {
        "openai": "OpenAI",
        "ollama": "Ollama",
        "local_ollama": "Ollama",
        "local-ollama": "Ollama",
        "openai-compatible": "OpenAI-compatible",
        "openai_compatible": "OpenAI-compatible",
        "openai-compatible-local": "OpenAI-compatible",
    }
    return labels.get(provider, provider.replace("_", " ").replace("-", " ").title())


def _model_list_url(provider: str, base_url: str) -> str:
    if provider in OLLAMA_PROVIDERS:
        return urljoin(base_url.rstrip("/") + "/", "api/tags")
    return urljoin(base_url.rstrip("/") + "/", "v1/models")


def _models_from_response(provider: str, payload: dict[str, Any]) -> set[str]:
    if provider in OLLAMA_PROVIDERS:
        return {
            _clean(model.get("name") or model.get("model"))
            for model in payload.get("models", [])
            if isinstance(model, dict)
        }
    return {
        _clean(model.get("id"))
        for model in payload.get("data", [])
        if isinstance(model, dict)
    }


def _remote_provider_status(
    *,
    slot: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    mode: str,
) -> ProviderStatus:
    if provider in DISABLED_PROVIDERS:
        return ProviderStatus(
            slot=slot,
            provider="disabled",
            provider_label="Disabled",
            configured=False,
            available=False,
            model=model,
            base_url=base_url,
            mode=mode,
            reason="provider disabled",
        )

    label = _provider_label(provider)

    if provider == "openai" and not base_url:
        if api_key:
            return ProviderStatus(
                slot=slot,
                provider=provider,
                provider_label=label,
                configured=True,
                available=True,
                model=model,
                base_url=base_url,
                mode=mode,
                reason="OpenAI API key configured",
            )
        return ProviderStatus(
            slot=slot,
            provider=provider,
            provider_label=label,
            configured=False,
            available=False,
            model=model,
            base_url=base_url,
            mode=mode,
            reason="OpenAI API key missing",
        )

    if not base_url:
        return ProviderStatus(
            slot=slot,
            provider=provider,
            provider_label=label,
            configured=False,
            available=False,
            model=model,
            base_url=base_url,
            mode=mode,
            reason="base URL missing",
        )

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(
            _model_list_url(provider, base_url),
            headers=headers,
            timeout=min(settings.llm_provider_timeout_seconds, REQUEST_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        models = _models_from_response(provider, response.json())
    except Exception as exc:
        return ProviderStatus(
            slot=slot,
            provider=provider,
            provider_label=label,
            configured=True,
            available=False,
            model=model,
            base_url=base_url,
            mode=mode,
            reason=f"health check failed: {exc}",
        )

    if model and model not in models:
        return ProviderStatus(
            slot=slot,
            provider=provider,
            provider_label=label,
            configured=True,
            available=False,
            model=model,
            base_url=base_url,
            mode=mode,
            reason=f"model {model!r} not available",
        )

    return ProviderStatus(
        slot=slot,
        provider=provider,
        provider_label=label,
        configured=True,
        available=True,
        model=model or next(iter(models), ""),
        base_url=base_url,
        mode=mode,
        reason="provider reachable",
    )


def _provider_statuses() -> list[ProviderStatus]:
    primary_model = _clean(settings.llm_primary_model) or _clean(
        settings.openai_default_model
    )
    primary_api_key = _clean(settings.llm_primary_api_key) or _clean(
        settings.openai_api_key
    )
    return [
        _remote_provider_status(
            slot="primary",
            provider=_clean(settings.llm_primary_provider).lower(),
            model=primary_model,
            base_url=_clean(settings.llm_primary_base_url),
            api_key=primary_api_key,
            mode="primary",
        ),
        _remote_provider_status(
            slot="backup",
            provider=_clean(settings.llm_backup_provider).lower(),
            model=_clean(settings.llm_backup_model),
            base_url=_clean(settings.llm_backup_base_url),
            api_key=_clean(settings.llm_backup_api_key),
            mode="backup_online",
        ),
        _remote_provider_status(
            slot="offline",
            provider=_clean(settings.llm_offline_provider).lower(),
            model=_clean(settings.llm_offline_model),
            base_url=_clean(settings.llm_offline_base_url),
            api_key=_clean(settings.llm_offline_api_key),
            mode="offline_local",
        ),
    ]


def get_llm_runtime_status() -> dict[str, Any]:
    providers = _provider_statuses()
    active = next((provider for provider in providers if provider.available), None)
    primary = providers[0]

    if active is None:
        return {
            "mode": "control_only",
            "mode_label": "Control only",
            "active_provider_label": "Unavailable",
            "active_model": "",
            "fallback_reason": "No configured LLM provider is currently available",
            "last_error": "; ".join(
                provider.reason for provider in providers if provider.configured
            ),
            "providers": [provider.as_dict() for provider in providers],
        }

    fallback_reason = ""
    if active.slot != "primary":
        fallback_reason = primary.reason or "primary provider unavailable"

    mode_labels = {
        "primary": "Primary",
        "backup_online": "Backup",
        "offline_local": "Offline",
    }

    return {
        "mode": active.mode,
        "mode_label": mode_labels.get(active.mode, active.mode),
        "active_provider_label": active.provider_label,
        "active_model": active.model,
        "fallback_reason": fallback_reason,
        "last_error": "" if active.slot == "primary" else primary.reason,
        "providers": [provider.as_dict() for provider in providers],
    }
