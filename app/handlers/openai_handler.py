from dataclasses import dataclass
from typing import List, Dict, Any
import anyio
from openai import OpenAI
from app.core.config import settings
from app.core.logging import setup_logger
from app.core.exceptions import APIError
from app.services.llm_runtime import record_llm_failure, record_llm_success
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.routing import NORLLAMA_PROVIDER_ALIASES

logger = setup_logger(__name__)

DEFAULT_MODEL = settings.openai_default_model
DEFAULT_MAX_TOKENS = settings.openai_max_tokens


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


@dataclass
class _ProviderAttempt:
    slot: str
    kind: str
    model: str
    label: str
    api_key: str = ""
    base_url: str = ""


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _provider_attempts(requested_model: str) -> list[_ProviderAttempt]:
    requested = _clean_str(requested_model) or DEFAULT_MODEL
    primary_kind = (
        _clean_str(getattr(settings, "llm_primary_provider", "openai")).lower()
        or "openai"
    )
    primary_api_key = _clean_str(
        getattr(settings, "llm_primary_api_key", "")
    ) or _clean_str(getattr(settings, "openai_api_key", ""))
    primary_base_url = _clean_str(getattr(settings, "llm_primary_base_url", ""))
    primary_model = _clean_str(getattr(settings, "llm_primary_model", "")) or requested

    backup_kind = (
        _clean_str(getattr(settings, "llm_backup_provider", "disabled")).lower()
        or "disabled"
    )
    backup_base_url = _clean_str(getattr(settings, "llm_backup_base_url", ""))
    backup_api_key = _clean_str(getattr(settings, "llm_backup_api_key", ""))
    backup_model = _clean_str(getattr(settings, "llm_backup_model", "")) or requested

    offline_kind = (
        _clean_str(getattr(settings, "llm_offline_provider", "disabled")).lower()
        or "disabled"
    )
    offline_base_url = _clean_str(getattr(settings, "llm_offline_base_url", ""))
    offline_api_key = _clean_str(getattr(settings, "llm_offline_api_key", ""))
    offline_model = _clean_str(getattr(settings, "llm_offline_model", "")) or requested

    attempts: list[_ProviderAttempt] = []
    if primary_kind == "openai" and primary_api_key:
        attempts.append(
            _ProviderAttempt(
                slot="primary",
                kind="openai",
                model=primary_model,
                label="OpenAI",
                api_key=primary_api_key,
                base_url=primary_base_url,
            )
        )
    elif (
        primary_kind == "openai_compatible" or primary_kind in NORLLAMA_PROVIDER_ALIASES
    ) and primary_base_url:
        attempts.append(
            _ProviderAttempt(
                slot="primary",
                kind=primary_kind,
                model=primary_model,
                label="Norllama"
                if primary_kind in NORLLAMA_PROVIDER_ALIASES
                else "Primary",
                api_key=primary_api_key,
                base_url=primary_base_url,
            )
        )

    if backup_kind != "disabled" and backup_base_url:
        attempts.append(
            _ProviderAttempt(
                slot="backup",
                kind=backup_kind,
                model=backup_model,
                label="Backup",
                api_key=backup_api_key,
                base_url=backup_base_url,
            )
        )

    if offline_kind != "disabled" and offline_base_url:
        attempts.append(
            _ProviderAttempt(
                slot="offline",
                kind=offline_kind,
                model=offline_model,
                label="Offline",
                api_key=offline_api_key,
                base_url=offline_base_url,
            )
        )
    return attempts


def _provider_client(attempt: _ProviderAttempt) -> OpenAI:
    if attempt.kind in NORLLAMA_PROVIDER_ALIASES:
        raise RuntimeError("Norllama providers use the Norllama gateway")
    if attempt.slot == "primary" and attempt.kind == "openai" and not attempt.base_url:
        return _client()
    api_key = attempt.api_key or "local"
    if attempt.base_url:
        return OpenAI(api_key=api_key, base_url=attempt.base_url)
    return OpenAI(api_key=api_key)


def _response_to_dict(response: Any) -> Dict[str, Any]:
    choices = []
    for choice in response.choices or []:
        content = getattr(choice.message, "content", None)
        choices.append({"message": {"content": content}})

    usage = response.usage
    usage_dict = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
    }

    return {
        "model": response.model,
        "choices": choices,
        "usage": usage_dict,
        "headers": {},
    }


async def create_chat_interaction(
    messages: List[Dict[str, str]],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str = DEFAULT_MODEL,
) -> Dict[str, str]:
    """
    Function to create a new chat interaction with OpenAI API.

    Args:
    model (str): Model name to be used for the chat.
    messages (List[Dict[str, str]]): List of message objects. Each object should have "role" and "content" fields.

    Returns:
    Dict[str, str]: Response from OpenAI API.

    The system role's content field should be from the "prompt" field in the Filter.
    The "user" role should be the incoming message
    The "assistant" role should be the response

    """

    try:
        attempts = _provider_attempts(model)
        if not attempts:
            raise ValueError("No LLM providers configured.")
        errors: dict[str, str] = {"primary": "", "backup": "", "offline": ""}
        first_failure = ""
        for attempt in attempts:
            try:
                if attempt.kind in NORLLAMA_PROVIDER_ALIASES:
                    payload = await anyio.to_thread.run_sync(
                        lambda: norllama_gateway.invoke_text_chat(
                            messages=messages,
                            model=attempt.model,
                            base_url=attempt.base_url,
                            api_key=attempt.api_key,
                            max_tokens=max_tokens,
                        )
                    )
                else:
                    response = await anyio.to_thread.run_sync(
                        lambda: _provider_client(attempt).chat.completions.create(
                            model=attempt.model,
                            messages=messages,
                            max_tokens=max_tokens,
                        )
                    )
                    payload = _response_to_dict(response)
                payload.setdefault("headers", {})
                payload["headers"].update(
                    {
                        "llm_provider": attempt.slot,
                        "llm_provider_kind": attempt.kind,
                        "llm_provider_label": attempt.label,
                        "llm_mode": (
                            "primary"
                            if attempt.slot == "primary"
                            else "backup_online"
                            if attempt.slot == "backup"
                            else "offline_local"
                        ),
                    }
                )
                if attempt.slot != "primary" and first_failure:
                    payload["headers"]["llm_fallback_reason"] = first_failure
                record_llm_success(
                    provider_slot=attempt.slot,
                    provider_kind=attempt.kind,
                    active_model=str(payload.get("model") or attempt.model),
                    fallback_reason=first_failure if attempt.slot != "primary" else "",
                    provider_label=attempt.label,
                )
                return payload
            except Exception as exc:
                message = str(exc)
                errors[attempt.slot] = message
                if not first_failure:
                    first_failure = message
                logger.warning(
                    "LLM provider attempt failed (%s/%s): %s",
                    attempt.slot,
                    attempt.kind,
                    exc,
                )
        record_llm_failure(
            last_error=first_failure or "All configured providers failed.",
            primary_error=errors["primary"],
            backup_error=errors["backup"],
            offline_error=errors["offline"],
        )
        raise APIError("Failed to communicate with configured LLM providers")

    except Exception as e:
        logger.error("Failed to create chat interaction: %s", e)
        if not _provider_attempts(model):
            logger.warning(
                "No LLM providers configured. Set primary, backup, or offline LLM settings and restart Norman."
            )
            response = {
                "model": "norman",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Please configure a primary, backup, or offline LLM provider in config.yaml and restart the program."
                            )
                        }
                    }
                ],
                "error": True,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "headers": {"llm_mode": "control_only"},
            }
            return response

        raise APIError("Failed to communicate with configured LLM providers") from e
