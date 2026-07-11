"""Connector-level OAuth helpers and pending-state storage."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings

_STATE_TTL_SECONDS = 10 * 60
_STATE_LOCK = threading.Lock()


@dataclass
class PendingConnectorOAuth:
    state: str
    user_id: int
    connector_id: int
    connector_type: str
    provider: str
    token_field: str
    created_at: float


_PENDING_STATES: Dict[str, PendingConnectorOAuth] = {}

_TOKEN_FIELD_BY_CONNECTOR: Dict[str, str] = {
    "google_chat": "service_account_key_path",
    "gmail": "password",
    "outlook": "password",
    "teams": "app_password",
    "discord": "token",
    "telegram": "token",
    "twitter": "access_token",
    "instagram_dm": "access_token",
    "facebook_messenger": "page_token",
    "linkedin": "access_token",
    "reddit_chat": "password",
    "github": "client_secret",
    "gitlab": "access_token",
    "intercom": "access_token",
    "salesforce": "refresh_token",
    "zoom": "client_secret",
}

_DEFAULT_SCOPES: Dict[str, List[str]] = {
    "google": ["openid", "email", "profile"],
    "microsoft": ["offline_access", "openid", "profile", "email", "User.Read"],
}

_CONNECTOR_SCOPES: Dict[Tuple[str, str], List[str]] = {
    ("google_chat", "google"): ["openid", "email", "profile"],
    ("gmail", "google"): [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    ("calendar", "google"): [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
    ("gdrive", "google"): [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/drive.readonly",
    ],
    ("bigquery", "google"): [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/bigquery.readonly",
    ],
    ("teams", "microsoft"): [
        "offline_access",
        "openid",
        "profile",
        "email",
        "User.Read",
    ],
    ("outlook", "microsoft"): [
        "offline_access",
        "openid",
        "profile",
        "email",
        "User.Read",
    ],
    ("outlook_calendar", "microsoft"): [
        "offline_access",
        "openid",
        "profile",
        "email",
        "User.Read",
    ],
}

_GOOGLE_FIRST_CONNECTORS = {
    "google_chat",
    "gmail",
    "calendar",
    "gdrive",
    "bigquery",
    "meet",
    "google_pubsub",
}

_MICROSOFT_FIRST_CONNECTORS = {
    "teams",
    "outlook",
    "outlook_calendar",
    "azure_eventgrid",
}


def _looks_like_placeholder(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith("your_") or value in {"change_me", "change_me_setup_key"}


def _provider_configured(provider: str) -> bool:
    settings = get_settings()
    if provider == "google":
        return bool(
            settings.google_client_id
            and settings.google_client_secret
            and not _looks_like_placeholder(settings.google_client_id)
            and not _looks_like_placeholder(settings.google_client_secret)
        )
    if provider == "microsoft":
        return bool(
            settings.microsoft_client_id
            and settings.microsoft_client_secret
            and not _looks_like_placeholder(settings.microsoft_client_id)
            and not _looks_like_placeholder(settings.microsoft_client_secret)
        )
    return False


def available_providers() -> List[str]:
    providers: List[str] = []
    for provider in ("google", "microsoft"):
        if _provider_configured(provider):
            providers.append(provider)
    return providers


def _providers_for_connector(connector_type: str) -> List[str]:
    providers = available_providers()
    if not providers:
        return []
    if connector_type in _GOOGLE_FIRST_CONNECTORS:
        return [provider for provider in ("google",) if provider in providers]
    if connector_type in _MICROSOFT_FIRST_CONNECTORS:
        return [provider for provider in ("microsoft",) if provider in providers]
    return providers


def oauth_capability(connector_type: str) -> Optional[Dict[str, object]]:
    providers = _providers_for_connector(connector_type)
    if not providers:
        return None
    default_provider = providers[0]
    scopes_by_provider = {
        provider: _CONNECTOR_SCOPES.get(
            (connector_type, provider), _DEFAULT_SCOPES[provider]
        )
        for provider in providers
    }
    return {
        "providers": providers,
        "default_provider": default_provider,
        "token_field": _TOKEN_FIELD_BY_CONNECTOR.get(
            connector_type, "oauth_access_token"
        ),
        "scopes_by_provider": scopes_by_provider,
    }


def resolve_oauth_binding(
    connector_type: str, provider: Optional[str] = None
) -> Dict[str, object]:
    providers = _providers_for_connector(connector_type)
    if not providers:
        raise ValueError("Connector SSO is not configured in Settings")
    selected_provider = provider or providers[0]
    if selected_provider not in providers:
        raise ValueError(f"Provider '{selected_provider}' is not configured")
    token_field = _TOKEN_FIELD_BY_CONNECTOR.get(connector_type, "oauth_access_token")
    scopes = _CONNECTOR_SCOPES.get(
        (connector_type, selected_provider), _DEFAULT_SCOPES[selected_provider]
    )
    return {
        "provider": selected_provider,
        "token_field": token_field,
        "scopes": scopes,
    }


def _cleanup_expired_states(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    expired = [
        key
        for key, item in _PENDING_STATES.items()
        if now - item.created_at > _STATE_TTL_SECONDS
    ]
    for key in expired:
        _PENDING_STATES.pop(key, None)


def create_pending_state(
    *,
    user_id: int,
    connector_id: int,
    connector_type: str,
    provider: str,
    token_field: str,
) -> str:
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _STATE_LOCK:
        _cleanup_expired_states(now=now)
        _PENDING_STATES[state] = PendingConnectorOAuth(
            state=state,
            user_id=user_id,
            connector_id=connector_id,
            connector_type=connector_type,
            provider=provider,
            token_field=token_field,
            created_at=now,
        )
    return state


def consume_pending_state(state: str, user_id: int) -> PendingConnectorOAuth:
    with _STATE_LOCK:
        _cleanup_expired_states()
        pending = _PENDING_STATES.pop(state, None)
    if not pending:
        raise ValueError("OAuth session expired or invalid state")
    if pending.user_id != user_id:
        raise ValueError("OAuth session does not belong to this user")
    return pending
