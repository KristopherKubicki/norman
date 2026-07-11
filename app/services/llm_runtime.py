from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import settings


def _now_ts() -> float:
    return time.time()


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _provider_kind_label(kind: str) -> str:
    normalized = _clean_str(kind).lower()
    if normalized == "openai":
        return "OpenAI"
    if normalized == "openai_compatible":
        return "OpenAI-compatible"
    if normalized in {"norllama", "ollama", "local_ollama", "local-ollama"}:
        return "Norllama"
    if normalized in {"bedrock", "aws-bedrock", "aws_bedrock"}:
        return "Bedrock"
    if normalized == "disabled":
        return "Disabled"
    return normalized or "Unknown"


def _provider_mode_label(mode: str) -> str:
    normalized = _clean_str(mode).lower()
    if normalized == "primary":
        return "Primary"
    if normalized == "backup_online":
        return "Backup"
    if normalized == "offline_local":
        return "Offline"
    if normalized == "control_only":
        return "Control only"
    return normalized or "Unknown"


@dataclass
class LlmProviderConfig:
    slot: str
    mode: str
    kind: str
    label: str
    configured: bool
    base_url: str = ""
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LlmRuntimeState:
    mode: str
    mode_label: str
    active_provider: str
    active_provider_label: str
    active_provider_kind: str
    active_model: str
    fallback_active: bool
    fallback_reason: str
    configured: bool
    providers: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
    last_primary_error: str = ""
    last_backup_error: str = ""
    last_offline_error: str = ""
    last_success_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_provider_configs() -> list[LlmProviderConfig]:
    primary_kind = _clean_str(
        getattr(settings, "llm_primary_provider", "openai")
    ).lower()
    if not primary_kind:
        primary_kind = "openai"
    primary_base_url = _clean_str(getattr(settings, "llm_primary_base_url", ""))
    primary_model = _clean_str(
        getattr(settings, "llm_primary_model", "")
    ) or _clean_str(getattr(settings, "openai_default_model", ""))
    primary_api_key = _clean_str(
        getattr(settings, "llm_primary_api_key", "")
    ) or _clean_str(getattr(settings, "openai_api_key", ""))
    primary_configured = False
    if primary_kind == "openai":
        primary_configured = bool(primary_api_key)
    elif primary_kind == "openai_compatible":
        primary_configured = bool(primary_base_url)

    backup_kind = (
        _clean_str(getattr(settings, "llm_backup_provider", "disabled")).lower()
        or "disabled"
    )
    backup_base_url = _clean_str(getattr(settings, "llm_backup_base_url", ""))
    backup_model = _clean_str(getattr(settings, "llm_backup_model", ""))
    backup_configured = backup_kind != "disabled" and bool(backup_base_url)

    offline_kind = (
        _clean_str(getattr(settings, "llm_offline_provider", "disabled")).lower()
        or "disabled"
    )
    offline_base_url = _clean_str(getattr(settings, "llm_offline_base_url", ""))
    offline_model = _clean_str(getattr(settings, "llm_offline_model", ""))
    offline_configured = offline_kind != "disabled" and bool(offline_base_url)

    return [
        LlmProviderConfig(
            slot="primary",
            mode="primary",
            kind=primary_kind,
            label=_provider_kind_label(primary_kind),
            configured=primary_configured,
            base_url=primary_base_url,
            model=primary_model,
        ),
        LlmProviderConfig(
            slot="backup",
            mode="backup_online",
            kind=backup_kind,
            label=_provider_kind_label(backup_kind),
            configured=backup_configured,
            base_url=backup_base_url,
            model=backup_model,
        ),
        LlmProviderConfig(
            slot="offline",
            mode="offline_local",
            kind=offline_kind,
            label=_provider_kind_label(offline_kind),
            configured=offline_configured,
            base_url=offline_base_url,
            model=offline_model,
        ),
    ]


_llm_state_lock = threading.Lock()
_llm_runtime_state = LlmRuntimeState(
    mode="control_only",
    mode_label="Control only",
    active_provider="",
    active_provider_label="Unavailable",
    active_provider_kind="disabled",
    active_model="",
    fallback_active=False,
    fallback_reason="",
    configured=False,
    updated_at=0.0,
)


def reset_llm_runtime_state() -> None:
    providers = _build_provider_configs()
    configured = any(item.configured for item in providers)
    mode = "primary" if providers and providers[0].configured else "control_only"
    active_provider = providers[0].slot if providers and providers[0].configured else ""
    active_provider_label = (
        providers[0].label if providers and providers[0].configured else "Unavailable"
    )
    active_provider_kind = (
        providers[0].kind if providers and providers[0].configured else "disabled"
    )
    active_model = providers[0].model if providers and providers[0].configured else ""
    with _llm_state_lock:
        _llm_runtime_state.mode = mode
        _llm_runtime_state.mode_label = _provider_mode_label(mode)
        _llm_runtime_state.active_provider = active_provider
        _llm_runtime_state.active_provider_label = active_provider_label
        _llm_runtime_state.active_provider_kind = active_provider_kind
        _llm_runtime_state.active_model = active_model
        _llm_runtime_state.fallback_active = False
        _llm_runtime_state.fallback_reason = ""
        _llm_runtime_state.configured = configured
        _llm_runtime_state.providers = [item.as_dict() for item in providers]
        _llm_runtime_state.last_error = ""
        _llm_runtime_state.last_primary_error = ""
        _llm_runtime_state.last_backup_error = ""
        _llm_runtime_state.last_offline_error = ""
        _llm_runtime_state.last_success_at = 0.0
        _llm_runtime_state.updated_at = 0.0


def get_llm_runtime_status() -> dict[str, Any]:
    providers = [item.as_dict() for item in _build_provider_configs()]
    configured = any(item["configured"] for item in providers)
    default_mode = "primary" if providers[0]["configured"] else "control_only"
    default_mode_label = _provider_mode_label(default_mode)
    default_provider = ""
    default_provider_label = "Unavailable"
    default_provider_kind = "disabled"
    default_model = ""
    if providers[0]["configured"]:
        default_provider = providers[0]["slot"]
        default_provider_label = providers[0]["label"]
        default_provider_kind = providers[0]["kind"]
        default_model = providers[0]["model"]

    with _llm_state_lock:
        state = _llm_runtime_state.as_dict()

    state["providers"] = providers
    state["configured"] = configured
    if not _clean_str(state.get("mode")):
        state["mode"] = default_mode
    if not _clean_str(state.get("mode_label")):
        state["mode_label"] = default_mode_label
    if not _clean_str(state.get("active_provider")):
        state["active_provider"] = default_provider
    if not _clean_str(state.get("active_provider_label")):
        state["active_provider_label"] = default_provider_label
    if not _clean_str(state.get("active_provider_kind")):
        state["active_provider_kind"] = default_provider_kind
    if not _clean_str(state.get("active_model")):
        state["active_model"] = default_model
    if state.get("mode") == "control_only" and configured:
        state["mode_label"] = _provider_mode_label("control_only")
    return state


def record_llm_success(
    *,
    provider_slot: str,
    provider_kind: str,
    active_model: str,
    fallback_reason: str = "",
    provider_label: str = "",
) -> None:
    mode = "control_only"
    fallback_active = False
    if provider_slot == "primary":
        mode = "primary"
    elif provider_slot == "backup":
        mode = "backup_online"
        fallback_active = True
    elif provider_slot == "offline":
        mode = "offline_local"
        fallback_active = True
    now = _now_ts()
    providers = _build_provider_configs()
    configured = any(item.configured for item in providers)
    label = provider_label or _provider_kind_label(provider_kind)
    with _llm_state_lock:
        _llm_runtime_state.mode = mode
        _llm_runtime_state.mode_label = _provider_mode_label(mode)
        _llm_runtime_state.active_provider = provider_slot
        _llm_runtime_state.active_provider_label = label
        _llm_runtime_state.active_provider_kind = provider_kind
        _llm_runtime_state.active_model = _clean_str(active_model)
        _llm_runtime_state.fallback_active = fallback_active
        _llm_runtime_state.fallback_reason = _clean_str(fallback_reason)
        _llm_runtime_state.configured = configured
        _llm_runtime_state.providers = [item.as_dict() for item in providers]
        _llm_runtime_state.last_error = ""
        _llm_runtime_state.last_success_at = now
        _llm_runtime_state.updated_at = now


def record_llm_failure(
    *,
    last_error: str,
    primary_error: str = "",
    backup_error: str = "",
    offline_error: str = "",
) -> None:
    now = _now_ts()
    providers = _build_provider_configs()
    configured = any(item.configured for item in providers)
    with _llm_state_lock:
        _llm_runtime_state.mode = "control_only"
        _llm_runtime_state.mode_label = _provider_mode_label("control_only")
        _llm_runtime_state.active_provider = ""
        _llm_runtime_state.active_provider_label = "Unavailable"
        _llm_runtime_state.active_provider_kind = "disabled"
        _llm_runtime_state.active_model = ""
        _llm_runtime_state.fallback_active = False
        _llm_runtime_state.fallback_reason = ""
        _llm_runtime_state.configured = configured
        _llm_runtime_state.providers = [item.as_dict() for item in providers]
        _llm_runtime_state.last_error = _clean_str(last_error)
        _llm_runtime_state.last_primary_error = _clean_str(primary_error)
        _llm_runtime_state.last_backup_error = _clean_str(backup_error)
        _llm_runtime_state.last_offline_error = _clean_str(offline_error)
        _llm_runtime_state.updated_at = now
