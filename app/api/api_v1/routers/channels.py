"""API routes for :class:`~app.models.channel.Channel`."""

import asyncio
import hashlib
import hmac
import inspect
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.crud.channel_message import create as create_channel_message_record
from app.crud.channel_message import get_by_channel as get_channel_message_records
from app.crud.channel_message import delete_by_channel as delete_channel_messages
from app.crud.channel_filter import delete_by_channel as delete_channel_filters
from app.models.action import Action
from app.models.channel_relay import ChannelRelay
from app.models.channel_message import ChannelMessage as ChannelMessageModel
from app.api.deps import get_db, get_current_user
from app.connectors.connector_utils import get_connector
from app.core.config import settings
from app.core.logging import setup_logger
from app.models import User
from app.schemas import (
    ChannelCreate,
    ChannelUpdate,
    Channel,
    ChannelMessageCreate,
    ChannelMessageOut,
)
from app.services.channel_feeds import feed_status, start_feed, stop_feed

router = APIRouter()
_OPERATOR_MODES = {"observe", "take", "co_pilot"}
_SUBPRIME_EXCLUDED_CONNECTORS = {"tmux:logs", "tmux:operator", "tmux:ops", "ops"}
# BBS fanout ACL is connector-config driven so root can enroll scoped machines
# without a migration. Fleet-wide coverage is only for broker/root roles.
_BBS_BROKER_ROLES = {"root", "broker", "operator"}
_BBS_SCOPED_ROLES = {"work", "personal", "network", "private"}
_BBS_PRIVATE_ZONES = {"private", "secret", "secrets", "vault"}
_BBS_PERSONAL_ZONES = {"personal"}
_BBS_WORK_ZONES = {"work", "office", "company"}
_BBS_NETWORK_ZONES = {
    "network",
    "net",
    "infra",
    "infrastructure",
    "dns",
    "caddy",
    "tailnet",
    "tailscale",
    "router",
    "routing",
}
_BBS_PRIVATE_KEYWORDS = (
    "private",
    "secret",
    "secrets",
    "vault",
    "finance",
    "health",
)
_BBS_PERSONAL_KEYWORDS = ("personal",)
_BBS_WORK_KEYWORDS = ("work", "office", "company")
_BBS_NETWORK_KEYWORDS = (
    "network",
    "net",
    "infra",
    "infrastructure",
    "dns",
    "caddy",
    "tailnet",
    "tailscale",
    "router",
    "routing",
)
_BBS_BROKER_KEYWORDS = (
    "norman bot prime",
    "norman prime",
    "switchboard",
    "root",
    "broker",
    "operator",
)
_BBS_ACL_CONFIG_KEYS = {
    "bbs_acl_role",
    "bbs_role",
    "bbs_zone",
    "bbs_scope",
    "bbs_receive",
    "bbs_channels",
    "bbs_allowed_channels",
    "bbs_boards",
    "bbs_full_coverage",
    "bbs_allow_private",
    "bbs_private_access",
    "bbs_cross_zone",
    "bbs_allow_cross_zone",
}
_PARTY_LINE_RELAY_MARKERS = (
    "[Norman Switchboard party line]",
    "[Norman Subprime party line]",
    "[Norman BBS party line]",
)
logger = setup_logger(__name__)


class ChannelFeedStart(BaseModel):
    source: str = Field(..., description="Feed source type")
    interval_seconds: int = Field(10, ge=1, le=3600)
    jitter_seconds: int = Field(0, ge=0, le=300)
    config: Dict[str, Any] = Field(default_factory=dict)


class ChannelOperatorRequest(BaseModel):
    mode: str = Field(..., description="Operator mode: observe, take, co_pilot")
    note: str = Field(default="", max_length=240)


class ChannelOperatorResponse(BaseModel):
    channel_id: int
    connector_id: int
    operator_mode: str
    operator_note: str = ""
    operator_updated_at: str = ""
    detail: str = ""


class ChannelRelayCallback(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=128)
    source_message_id: int = Field(..., ge=1)
    status: str = Field(default="closed", max_length=32)
    success: bool | None = None
    target: str = Field(default="", max_length=160)
    target_connector_id: int | None = Field(default=None, ge=1)
    target_connector_name: str = Field(default="", max_length=160)
    thread_id: str = Field(default="", max_length=160)
    summary: str = Field(default="", max_length=1200)


class ChannelRelayOut(BaseModel):
    id: int
    relay_id: str
    channel_id: int
    source_message_id: int
    source_connector_id: int | None = None
    target_connector_id: int | None = None
    target_name: str = ""
    status: str
    success: bool | None = None
    attempts: int = 0
    last_error: str = ""
    summary: str = ""
    thread_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    accepted_at: datetime | None = None
    closed_at: datetime | None = None
    stale_at: datetime | None = None

    class Config:
        orm_mode = True


class ChannelRelaySweepResponse(BaseModel):
    channel_id: int
    stale_count: int
    relays: list[ChannelRelayOut] = Field(default_factory=list)


_RELAY_CALLBACK_STATUSES = {
    "queued",
    "picked_up",
    "accepted",
    "running",
    "closed",
    "completed",
    "failed",
    "stale",
}
_RELAY_OPEN_STATUSES = {
    "created",
    "fanout_attempted",
    "accepted",
    "queued",
    "picked_up",
    "running",
}
_RELAY_TERMINAL_STATUSES = {"closed", "failed", "stale", "expired"}
_RELAY_DEFAULT_STALE_SECONDS = 15 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _relay_callback_token(
    channel_id: int, source_message_id: int, relay_id: str
) -> str:
    secret = str(settings.secret_key or "").encode("utf-8")
    message = f"{int(channel_id)}:{int(source_message_id)}:{relay_id}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _verify_relay_callback_token(
    channel_id: int, source_message_id: int, relay_id: str, token: str
) -> bool:
    expected = _relay_callback_token(channel_id, source_message_id, relay_id)
    return hmac.compare_digest(expected, str(token or "").strip())


def _relay_callback_url(
    request: Request, *, channel_id: int, source_message_id: int, relay_id: str
) -> str:
    token = _relay_callback_token(channel_id, source_message_id, relay_id)
    base_url = str(
        request.url_for("create_channel_relay_callback", channel_id=channel_id)
    )
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'relay_token': token})}"


def _normalize_relay_callback_status(status: str, success: bool | None) -> str:
    normalized = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "completed":
        normalized = "closed"
    if normalized not in _RELAY_CALLBACK_STATUSES:
        normalized = "failed" if success is False else "closed"
    return normalized


def _relay_target_label(connector=None, *, fallback: str = "") -> str:
    if connector is not None:
        cfg = dict(getattr(connector, "config", None) or {})
        label = str(cfg.get("label") or "").strip()
        if label:
            return label
        name = str(getattr(connector, "name", "") or "").strip()
        if name:
            return name
    return str(fallback or "").strip() or "agent"


def _normalize_relay_datetime(value: datetime | None) -> datetime:
    if not isinstance(value, datetime):
        return _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _relay_last_activity_at(relay: ChannelRelay) -> datetime:
    return max(
        _normalize_relay_datetime(getattr(relay, "updated_at", None)),
        _normalize_relay_datetime(getattr(relay, "accepted_at", None)),
        _normalize_relay_datetime(getattr(relay, "created_at", None)),
    )


def _relay_status_from_collector_response(response: Any) -> str:
    if isinstance(response, dict):
        status_value = str(response.get("status") or "").strip().lower()
        if status_value in _RELAY_CALLBACK_STATUSES:
            return _normalize_relay_callback_status(
                status_value, response.get("success")
            )
        if response.get("queued") is True:
            return "queued"
        if response.get("accepted") is True:
            return "accepted"
    return "accepted"


def _upsert_channel_relay(
    db: Session,
    *,
    relay_id: str,
    channel_id: int,
    source_message_id: int,
    source_connector_id: int | None,
    target_connector_id: int | None,
    target_name: str,
    callback_url: str,
    status_value: str,
    success: bool | None = None,
    summary: str = "",
    thread_id: str = "",
    last_error: str = "",
    payload: dict[str, Any] | None = None,
    increment_attempts: bool = False,
) -> ChannelRelay:
    status_text = _normalize_relay_callback_status(status_value, success)
    if status_text == "closed" and status_value not in {"closed", "completed"}:
        status_text = str(status_value or "accepted").strip().lower() or "accepted"
    relay = (
        db.query(ChannelRelay)
        .filter(ChannelRelay.relay_id == relay_id)
        .filter(ChannelRelay.channel_id == int(channel_id))
        .filter(ChannelRelay.source_message_id == int(source_message_id))
        .filter(ChannelRelay.target_connector_id == target_connector_id)
        .first()
    )
    now = _utcnow()
    if relay is None:
        relay = ChannelRelay(
            relay_id=relay_id,
            channel_id=int(channel_id),
            source_message_id=int(source_message_id),
            source_connector_id=source_connector_id,
            target_connector_id=target_connector_id,
            target_name=target_name,
            callback_url=callback_url,
            status=status_text,
            created_at=now,
        )
        db.add(relay)
    relay.target_name = str(target_name or relay.target_name or "agent").strip()
    relay.callback_url = str(callback_url or relay.callback_url or "").strip()
    relay.status = status_text
    relay.success = success
    relay.summary = str(summary or relay.summary or "").strip()
    relay.thread_id = str(thread_id or relay.thread_id or "").strip()
    relay.last_error = str(last_error or "").strip()
    relay.payload = payload or relay.payload or {}
    relay.updated_at = now
    if increment_attempts:
        relay.attempts = int(relay.attempts or 0) + 1
    if status_text in {"accepted", "queued", "picked_up", "running"}:
        relay.accepted_at = relay.accepted_at or now
    if status_text in {"closed", "failed"}:
        relay.closed_at = now
    if status_text == "stale":
        relay.stale_at = now
    db.commit()
    db.refresh(relay)
    return relay


def _matching_callback_relays(
    db: Session, *, channel_id: int, payload: ChannelRelayCallback
) -> list[ChannelRelay]:
    query = (
        db.query(ChannelRelay)
        .filter(ChannelRelay.channel_id == int(channel_id))
        .filter(ChannelRelay.source_message_id == int(payload.source_message_id))
        .filter(ChannelRelay.relay_id == payload.relay_id)
    )
    target_connector_id = payload.target_connector_id
    if target_connector_id:
        exact = query.filter(
            ChannelRelay.target_connector_id == int(target_connector_id)
        ).all()
        if exact:
            return exact
    target_label = (
        str(payload.target_connector_name or "").strip()
        or str(payload.target or "").strip()
    )
    if target_label:
        by_name = query.filter(ChannelRelay.target_name == target_label).all()
        if by_name:
            return by_name
    relays = query.all()
    open_relays = [
        relay
        for relay in relays
        if str(relay.status or "").strip().lower() in _RELAY_OPEN_STATUSES
    ]
    return open_relays or relays


def _record_relay_callback(
    db: Session, *, channel_id: int, payload: ChannelRelayCallback
) -> tuple[list[ChannelRelay], bool]:
    status_text = _normalize_relay_callback_status(payload.status, payload.success)
    target_name = (
        str(payload.target_connector_name or "").strip()
        or str(payload.target or "").strip()
        or "agent"
    )
    relays = _matching_callback_relays(db, channel_id=channel_id, payload=payload)
    if not relays:
        relay = _upsert_channel_relay(
            db,
            relay_id=payload.relay_id,
            channel_id=channel_id,
            source_message_id=payload.source_message_id,
            source_connector_id=None,
            target_connector_id=payload.target_connector_id,
            target_name=target_name,
            callback_url="",
            status_value=status_text,
            success=payload.success,
            summary=payload.summary,
            thread_id=payload.thread_id,
        )
        return [relay], True
    changed = False
    now = _utcnow()
    for relay in relays:
        previous_status = str(relay.status or "").strip().lower()
        previous_closed = relay.closed_at
        if previous_status != status_text or previous_closed is None:
            changed = True
        relay.status = status_text
        relay.success = payload.success
        relay.target_name = target_name or relay.target_name
        relay.summary = str(payload.summary or relay.summary or "").strip()
        relay.thread_id = str(payload.thread_id or relay.thread_id or "").strip()
        relay.updated_at = now
        if status_text in {"accepted", "queued", "picked_up", "running"}:
            relay.accepted_at = relay.accepted_at or now
        if status_text in {"closed", "failed"}:
            relay.closed_at = relay.closed_at or now
        if status_text == "stale":
            relay.stale_at = relay.stale_at or now
        db.add(relay)
    db.commit()
    for relay in relays:
        db.refresh(relay)
    return relays, changed


def _relay_callback_content(payload: ChannelRelayCallback) -> str:
    status_text = _normalize_relay_callback_status(payload.status, payload.success)
    target = (
        str(payload.target_connector_name or "").strip()
        or str(payload.target or "agent").strip()
    )
    summary = re.sub(r"\s+", " ", str(payload.summary or "").strip())
    if not summary:
        summary = (
            "Relay callback completed."
            if status_text == "closed"
            else "Relay callback reported status."
        )
    lines = [
        f"[Norman BBS relay {status_text}]",
        f"Relay id: {payload.relay_id}",
        f"Source message: {payload.source_message_id}",
        f"Target: {target}",
    ]
    thread_id = str(payload.thread_id or "").strip()
    if thread_id:
        lines.append(f"Thread: {thread_id}")
    lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def _relay_stale_content(relay: ChannelRelay) -> str:
    return "\n".join(
        [
            "[Norman BBS relay stale]",
            f"Relay id: {relay.relay_id}",
            f"Source message: {relay.source_message_id}",
            f"Target: {relay.target_name or 'agent'}",
            f"Last status: {relay.status or 'unknown'}",
            "Summary: No relay callback landed before the stale threshold.",
        ]
    )


def _latest_relay_callback_message(
    db: Session, *, channel_id: int, relay_id: str, status_text: str
):
    marker = f"[Norman BBS relay {status_text}]"
    relay_line = f"Relay id: {relay_id}"
    return (
        db.query(ChannelMessageModel)
        .filter(ChannelMessageModel.channel_id == int(channel_id))
        .filter(ChannelMessageModel.source == "relay-callback")
        .filter(ChannelMessageModel.content.contains(marker))
        .filter(ChannelMessageModel.content.contains(relay_line))
        .order_by(ChannelMessageModel.created_at.desc())
        .first()
    )


def _mark_stale_channel_relays(
    db: Session, *, channel_id: int, stale_after_seconds: int
) -> list[ChannelRelay]:
    threshold = _utcnow() - timedelta(seconds=max(1, int(stale_after_seconds or 1)))
    candidates = (
        db.query(ChannelRelay)
        .filter(ChannelRelay.channel_id == int(channel_id))
        .filter(ChannelRelay.status.in_(sorted(_RELAY_OPEN_STATUSES)))
        .all()
    )
    stale_relays: list[ChannelRelay] = []
    for relay in candidates:
        if _relay_last_activity_at(relay) > threshold:
            continue
        relay.status = "stale"
        relay.success = False
        relay.summary = "No relay callback landed before the stale threshold."
        relay.last_error = relay.last_error or "relay callback timeout"
        relay.updated_at = _utcnow()
        relay.stale_at = relay.updated_at
        db.add(relay)
        stale_relays.append(relay)
    if not stale_relays:
        return []
    db.commit()
    refreshed: list[ChannelRelay] = []
    for relay in stale_relays:
        db.refresh(relay)
        create_channel_message_record(
            db,
            int(channel_id),
            ChannelMessageCreate(content=_relay_stale_content(relay)),
            source="relay-watchdog",
        )
        refreshed.append(relay)
    return refreshed


def _normalize_operator_mode(value: str | None, *, strict: bool = False) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "auto": "observe",
        "manual": "take",
        "shared": "co_pilot",
        "copilot": "co_pilot",
        "release": "observe",
    }
    normalized = aliases.get(text, text or "observe")
    if normalized not in _OPERATOR_MODES:
        if strict:
            raise HTTPException(status_code=400, detail="Unsupported operator mode")
        return "observe"
    return normalized


def _channel_operator_modes(config: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = (config or {}).get("channel_operator_modes")
    return raw if isinstance(raw, dict) else {}


def _channel_operator_state(channel, connector) -> Dict[str, str]:
    states = _channel_operator_modes(getattr(connector, "config", None))
    raw = states.get(str(getattr(channel, "id", "")), {})
    if isinstance(raw, str):
        return {
            "operator_mode": _normalize_operator_mode(raw),
            "operator_note": "",
            "operator_updated_at": "",
        }
    if not isinstance(raw, dict):
        raw = {}
    return {
        "operator_mode": _normalize_operator_mode(raw.get("mode")),
        "operator_note": str(raw.get("note") or "").strip(),
        "operator_updated_at": str(raw.get("updated_at") or "").strip(),
    }


def _attach_channel_operator_state(channel, connector):
    state = _channel_operator_state(channel, connector)
    channel.operator_mode = state["operator_mode"]
    channel.operator_note = state["operator_note"]
    channel.operator_updated_at = state["operator_updated_at"]
    return channel


def _normalize_channel_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _is_switchboard_party_line(channel) -> bool:
    key = _normalize_channel_key(getattr(channel, "name", ""))
    return key in {
        "console switchboard",
        "switchboard",
        "console subprime",
        "subprime",
    }


def _is_party_line_relay_content(content: str | None) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    return any(text.startswith(marker) for marker in _PARTY_LINE_RELAY_MARKERS)


def _connector_config(connector) -> dict[str, Any]:
    return dict(getattr(connector, "config", None) or {})


def _normalize_acl_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9*]+", " ", str(value or "").strip().lower()).strip()


def _config_bool(config: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled", "allow"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled", "deny"}:
            return False
    return default


def _config_list(config: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(part).strip() for part in value if str(part).strip()]
        text = str(value).strip()
        return [text] if text else []
    return []


def _connector_identity_key(connector) -> str:
    cfg = _connector_config(connector)
    parts = [
        getattr(connector, "name", ""),
        cfg.get("label", ""),
        cfg.get("host", ""),
        cfg.get("hostname", ""),
        cfg.get("collector_url", ""),
        cfg.get("web_url", ""),
    ]
    return _normalize_acl_token(" ".join(str(part or "") for part in parts))


def _connector_identity_has(connector, keywords: tuple[str, ...]) -> bool:
    identity = _connector_identity_key(connector)
    identity_tokens = set(identity.split())
    for keyword in keywords:
        normalized = _normalize_acl_token(keyword)
        if not normalized:
            continue
        if " " in normalized:
            if normalized in identity:
                return True
            continue
        if normalized in identity_tokens:
            return True
    return False


def _canonical_bbs_zone(value: Any) -> str:
    zone = _normalize_acl_token(value)
    if not zone:
        return ""
    if zone in _BBS_PRIVATE_ZONES:
        return "private"
    if zone in _BBS_PERSONAL_ZONES:
        return "personal"
    if zone in _BBS_WORK_ZONES:
        return "work"
    if zone in _BBS_NETWORK_ZONES:
        return "network"
    return zone


def _connector_bbs_role(connector) -> str:
    cfg = _connector_config(connector)
    configured = cfg.get("bbs_acl_role") or cfg.get("bbs_role")
    role = _normalize_acl_token(configured)
    if role in _BBS_BROKER_ROLES or role in _BBS_SCOPED_ROLES:
        return role
    if role in {"off", "none", "disabled", "deny"}:
        return "disabled"
    if _connector_identity_has(connector, _BBS_PRIVATE_KEYWORDS):
        return "private"
    if _connector_identity_has(connector, _BBS_PERSONAL_KEYWORDS):
        return "personal"
    if _connector_identity_has(connector, _BBS_NETWORK_KEYWORDS):
        return "network"
    if _connector_identity_has(connector, _BBS_WORK_KEYWORDS):
        return "work"
    if _connector_identity_has(connector, _BBS_BROKER_KEYWORDS):
        return "broker"
    return "legacy"


def _connector_bbs_zone(connector) -> str:
    cfg = _connector_config(connector)
    configured = cfg.get("bbs_zone") or cfg.get("bbs_scope")
    zone = _canonical_bbs_zone(configured)
    if zone:
        return zone
    role = _connector_bbs_role(connector)
    if role in _BBS_SCOPED_ROLES:
        return _canonical_bbs_zone(role) or role
    return "global"


def _channel_bbs_zone(channel) -> str:
    key = _normalize_channel_key(getattr(channel, "name", ""))
    if not key:
        return "global"
    first = key.split(" ", 1)[0]
    zone = _canonical_bbs_zone(first)
    if zone in {"private", "personal", "work", "network"}:
        return zone
    if first in {"switchboard", "subprime", "bbs", "global", "console"}:
        return "global"
    return "global"


def _connector_has_explicit_bbs_acl(connector) -> bool:
    cfg = _connector_config(connector)
    return any(key in cfg for key in _BBS_ACL_CONFIG_KEYS)


def _connector_bbs_channel_patterns(connector) -> list[str]:
    cfg = _connector_config(connector)
    return _config_list(
        cfg,
        "bbs_channels",
        "bbs_allowed_channels",
        "bbs_boards",
    )


def _bbs_channel_patterns_match(
    patterns: list[str], *, channel_key: str, channel_zone: str
) -> bool:
    if not patterns:
        return False
    normalized_channel = _normalize_acl_token(channel_key)
    normalized_zone = _normalize_acl_token(channel_zone)
    for raw_pattern in patterns:
        raw = str(raw_pattern or "").strip().lower()
        if raw in {"*", "all"}:
            return True
        if raw.endswith("/*"):
            prefix = _normalize_acl_token(raw[:-2])
            if prefix and (
                normalized_zone == prefix or normalized_channel.startswith(prefix)
            ):
                return True
            continue
        pattern = _normalize_acl_token(raw)
        if pattern in {normalized_channel, normalized_zone}:
            return True
    return False


def _connector_bbs_receive_enabled(connector) -> bool:
    cfg = _connector_config(connector)
    role = _connector_bbs_role(connector)
    if role == "disabled":
        return False
    if "bbs_receive" in cfg:
        return _config_bool(cfg, "bbs_receive", default=False)
    if role == "private" or _connector_requires_private_bbs_grant(connector):
        return False
    return True


def _connector_has_full_bbs_coverage(connector) -> bool:
    cfg = _connector_config(connector)
    if "bbs_full_coverage" in cfg:
        return _config_bool(cfg, "bbs_full_coverage", default=False)
    role = _connector_bbs_role(connector)
    return role in _BBS_BROKER_ROLES


def _connector_allows_cross_zone_bbs_coverage(connector) -> bool:
    cfg = _connector_config(connector)
    if _config_bool(cfg, "bbs_cross_zone", "bbs_allow_cross_zone", default=False):
        return True
    return _connector_bbs_role(connector) in _BBS_BROKER_ROLES


def _connector_allows_private_bbs_coverage(connector) -> bool:
    cfg = _connector_config(connector)
    if _config_bool(cfg, "bbs_allow_private", "bbs_private_access", default=False):
        return True
    role = _connector_bbs_role(connector)
    return role in {"root", "operator"}


def _connector_requires_private_bbs_grant(connector) -> bool:
    return (
        _connector_bbs_zone(connector) in _BBS_PRIVATE_ZONES
        or _connector_bbs_role(connector) == "private"
        or _connector_identity_has(connector, _BBS_PRIVATE_KEYWORDS)
    )


def _switchboard_party_line_acl_decision(channel, source_connector, target_connector):
    if not _connector_bbs_receive_enabled(target_connector):
        return False, "target_receive_disabled"

    channel_key = _normalize_channel_key(getattr(channel, "name", ""))
    channel_zone = _channel_bbs_zone(channel)
    source_role = _connector_bbs_role(source_connector)
    source_zone = _connector_bbs_zone(source_connector)
    target_zone = _connector_bbs_zone(target_connector)
    source_full_coverage = _connector_has_full_bbs_coverage(source_connector)
    source_cross_zone = _connector_allows_cross_zone_bbs_coverage(source_connector)
    source_patterns = _connector_bbs_channel_patterns(source_connector)
    target_patterns = _connector_bbs_channel_patterns(target_connector)
    target_has_acl = _connector_has_explicit_bbs_acl(target_connector)
    target_matches_channel = _bbs_channel_patterns_match(
        target_patterns,
        channel_key=channel_key,
        channel_zone=channel_zone,
    )

    if source_role == "disabled":
        return False, "source_disabled"
    if source_patterns and not _bbs_channel_patterns_match(
        source_patterns,
        channel_key=channel_key,
        channel_zone=channel_zone,
    ):
        return False, "source_channel_not_allowed"
    if (
        channel_zone != "global"
        and source_zone != "global"
        and channel_zone != source_zone
        and not source_cross_zone
    ):
        return False, "source_channel_zone_mismatch"
    if target_patterns and not target_matches_channel:
        return False, "target_channel_not_allowed"

    if _connector_requires_private_bbs_grant(target_connector):
        if not target_matches_channel:
            return False, "private_target_requires_channel_grant"
        if not source_full_coverage:
            return False, "private_target_requires_broker"
        if (
            source_zone != "global"
            and source_zone != target_zone
            and not source_cross_zone
        ):
            return False, "zone_mismatch"
        if not _connector_allows_private_bbs_coverage(source_connector):
            return False, "private_target_requires_private_source_grant"
        return True, "private_explicit"

    if source_full_coverage:
        if (
            source_zone != "global"
            and source_zone != target_zone
            and not source_cross_zone
        ):
            return False, "zone_mismatch"
        if target_patterns:
            return True, "broker_channel_grant"
        if source_zone != "global" and source_zone == target_zone and target_has_acl:
            return True, "zone_full_coverage"
        if target_zone == "global":
            return True, "broker_global_legacy"
        return False, "scoped_target_requires_channel_grant"

    if source_zone != target_zone:
        return False, "zone_mismatch"
    if channel_zone == "global" and not target_matches_channel:
        return False, "global_channel_requires_explicit_target_grant"
    if target_has_acl or target_matches_channel:
        return True, "scoped_explicit"
    return False, "scoped_target_requires_explicit_acl"


def _channel_outbound_payload(channel, content: str, connector_instance: Any) -> Any:
    """Return the most likely payload shape for connector manual sends."""

    payload = {
        "text": content,
        "channel_id": int(channel.id),
        "channel_name": channel.name,
    }
    try:
        signature = inspect.signature(connector_instance.send_message)
        params = [
            param for param in signature.parameters.values() if param.name != "self"
        ]
        if not params:
            return content
        annotation = params[0].annotation
        if annotation is inspect._empty:
            return content
        annotation_text = str(annotation).lower()
        if annotation is dict or "dict" in annotation_text:
            return payload
    except (TypeError, ValueError):
        return content
    return content


def _payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        command = payload.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return ""
    if isinstance(payload, str):
        return payload.strip()
    return str(payload or "").strip()


def _connector_web_token(connector) -> str:
    cfg = dict(getattr(connector, "config", None) or {})
    return str(cfg.get("web_token") or "").strip()


def _connector_collector_url(connector) -> str:
    cfg = dict(getattr(connector, "config", None) or {})
    return str(cfg.get("collector_url") or cfg.get("web_url") or "").strip()


def _console_action_url(
    base_url: str, action_path: str, *, access_token: str = ""
) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    if not parts.scheme or not parts.netloc:
        return ""
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    token = (
        str(access_token or "").strip() or str(query_items.get("token") or "").strip()
    )
    action_query = {"token": token} if token else {}
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            action_path,
            urlencode(action_query),
            "",
        )
    )


async def _send_tmux_collector_message(
    connector, payload: Any, *, timeout: float = 8.0
) -> dict[str, Any]:
    text = _payload_text(payload)
    if not text:
        return {"status": "ignored", "reason": "empty_message"}

    action_url = _console_action_url(
        _connector_collector_url(connector),
        "/api/ask",
        access_token=_connector_web_token(connector),
    )
    if not action_url:
        raise RuntimeError("tmux collector URL is unavailable")

    form_payload = {"message": text}
    if isinstance(payload, dict):
        for key in (
            "party_line_relay",
            "relay_id",
            "relay_callback_url",
            "relay_source_channel_id",
            "relay_source_message_id",
            "relay_source_connector_id",
            "relay_source_connector_name",
            "relay_target_connector_id",
            "relay_target_connector_name",
            "speed",
            "detail",
        ):
            value = payload.get(key)
            if value is None or value == "":
                continue
            form_payload[key] = str(value)

    body = urlencode(form_payload).encode("utf-8")
    request = urllib_request.Request(
        action_url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "NormanPrime/1.0",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib_error.HTTPError as exc:
        detail = "Remote console rejected the Switchboard broadcast."
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                detail = str(payload.get("error") or detail)
        except (ValueError, json.JSONDecodeError):
            pass
        raise RuntimeError(detail) from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Remote console broadcast failed: {exc}") from exc

    try:
        parsed = json.loads(raw) if raw else {}
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Remote console returned an invalid response.") from exc
    if isinstance(parsed, dict) and parsed.get("accepted") is False:
        raise RuntimeError(str(parsed.get("error") or "Remote console is busy."))
    return parsed if isinstance(parsed, dict) else {}


async def _send_connector_message(connector, payload: Any) -> Any:
    if str(
        getattr(connector, "connector_type", "") or ""
    ).strip().lower() == "tmux" and _connector_collector_url(connector):
        return await _send_tmux_collector_message(connector, payload)
    instance = get_connector(connector.connector_type, connector.config or {})
    result = instance.send_message(payload)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _deliver_channel_message(channel, connector, content: str) -> None:
    """Send a manual outbound message through the channel's connector."""

    instance = get_connector(connector.connector_type, connector.config or {})
    primary_payload = _channel_outbound_payload(channel, content, instance)
    fallback_payload = (
        {"text": content, "channel_id": int(channel.id), "channel_name": channel.name}
        if not isinstance(primary_payload, dict)
        else content
    )
    last_error: Exception | None = None

    for attempt_index, outbound_payload in enumerate(
        (primary_payload, fallback_payload)
    ):
        if attempt_index == 1 and outbound_payload == primary_payload:
            continue
        try:
            await _send_connector_message(connector, outbound_payload)
            return
        except (TypeError, AttributeError, KeyError) as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break

    detail = str(last_error or "Unable to deliver message")
    raise HTTPException(status_code=502, detail=detail)


def _switchboard_party_line_targets(
    db: Session, user_id: int, channel, source_connector
):
    targets = []
    skipped: dict[str, int] = {}
    for connector in crud.connector.get_multi_by_user(db, user_id):
        if int(connector.id) == int(source_connector.id):
            continue
        if str(connector.connector_type or "").strip().lower() != "tmux":
            continue
        name_key = str(connector.name or "").strip().lower()
        if name_key in _SUBPRIME_EXCLUDED_CONNECTORS:
            continue
        allowed, reason = _switchboard_party_line_acl_decision(
            channel, source_connector, connector
        )
        if not allowed:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        targets.append(connector)
    if skipped:
        logger.info(
            "Switchboard party line fanout skipped targets by ACL",
            extra={
                "channel": str(getattr(channel, "name", "") or ""),
                "source_connector": str(
                    getattr(source_connector, "name", None)
                    or getattr(source_connector, "id", "")
                ),
                "skipped": skipped,
            },
        )
    return targets


async def _fanout_switchboard_party_line(
    db: Session,
    *,
    user_id: int,
    channel,
    source_connector,
    source_message,
    content: str,
    relay_id: str,
    relay_callback_url: str,
) -> None:
    targets = _switchboard_party_line_targets(db, user_id, channel, source_connector)
    if not targets:
        return

    base_payload = {
        "text": (
            "[Norman Switchboard party line]\n"
            "Passive fleet context only. Absorb this silently unless you are directly addressed or explicitly asked to act.\n\n"
            "Loop closure: this is a closed relay. Do not echo, acknowledge, repost, or route it back to the BBS/Switchboard unless directly addressed.\n\n"
            f"{content.strip()}"
        ),
        "channel_id": int(channel.id),
        "channel_name": channel.name,
        "party_line_relay": True,
        "relay_id": relay_id,
        "relay_callback_url": relay_callback_url,
        "relay_source_channel_id": int(channel.id),
        "relay_source_message_id": int(source_message.id),
        "relay_source_connector_id": int(source_connector.id),
        "relay_source_connector_name": str(source_connector.name or ""),
        "speed": "careful",
        "detail": 5,
        "submit_mode": "tab_enter",
        "enter_count": 1,
    }

    failures: list[str] = []
    delivered = 0
    for connector in targets:
        target_name = _relay_target_label(connector)
        payload = {
            **base_payload,
            "relay_target_connector_id": int(connector.id),
            "relay_target_connector_name": target_name,
        }
        _upsert_channel_relay(
            db,
            relay_id=relay_id,
            channel_id=int(channel.id),
            source_message_id=int(source_message.id),
            source_connector_id=int(source_connector.id),
            target_connector_id=int(connector.id),
            target_name=target_name,
            callback_url=relay_callback_url,
            status_value="fanout_attempted",
            payload={"collector_url": _connector_collector_url(connector)},
            increment_attempts=True,
        )
        try:
            response = await _send_connector_message(connector, payload)
            _upsert_channel_relay(
                db,
                relay_id=relay_id,
                channel_id=int(channel.id),
                source_message_id=int(source_message.id),
                source_connector_id=int(source_connector.id),
                target_connector_id=int(connector.id),
                target_name=target_name,
                callback_url=relay_callback_url,
                status_value=_relay_status_from_collector_response(response),
                payload={
                    "collector_url": _connector_collector_url(connector),
                    "collector_response": response
                    if isinstance(response, dict)
                    else {},
                },
            )
            delivered += 1
        except Exception as exc:  # pragma: no cover - defensive logging path
            _upsert_channel_relay(
                db,
                relay_id=relay_id,
                channel_id=int(channel.id),
                source_message_id=int(source_message.id),
                source_connector_id=int(source_connector.id),
                target_connector_id=int(connector.id),
                target_name=target_name,
                callback_url=relay_callback_url,
                status_value="failed",
                success=False,
                last_error=str(exc),
                payload={"collector_url": _connector_collector_url(connector)},
            )
            failures.append(f"{connector.name}: {exc}")

    logger.info(
        "Switchboard party line fanout attempted",
        extra={
            "channel": str(channel.name or ""),
            "source_connector": str(source_connector.name or source_connector.id),
            "delivered": delivered,
            "failed": len(failures),
        },
    )
    if failures:
        logger.warning(
            "Switchboard party line fanout failures: %s", "; ".join(failures)
        )


# Your endpoints and handlers go here


@router.post("", response_model=Channel, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=Channel, status_code=status.HTTP_201_CREATED)
async def create_channel(
    channel: ChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new channel.

    Args:
        channel: Channel data to persist.
        db: Database session dependency.

    Returns:
        The created channel instance.

    Raises:
        HTTPException: If the channel could not be created.
    """
    try:
        connector = crud.connector.get(db, channel.connector_id)
        if not connector or connector.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
        created = crud.channel.create(db, obj_in=channel)
        return _attach_channel_operator_state(created, connector)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=List[Channel])
@router.get("/", response_model=List[Channel])
async def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all channels.

    Args:
        db: Database session dependency.

    Returns:
        List of channels.
    """
    channels = crud.channel.get_multi_by_user(db, current_user.id)
    connectors = {
        int(connector.id): connector
        for connector in crud.connector.get_multi_by_user(db, current_user.id)
    }
    return [
        _attach_channel_operator_state(
            channel, connectors.get(int(channel.connector_id))
        )
        for channel in channels
    ]


@router.get("/{channel_id}", response_model=Channel)
async def get_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a channel by ID.

    Args:
        channel_id: Identifier of the channel to fetch.
        db: Database session dependency.

    Returns:
        The requested channel.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    connector = crud.connector.get(db, int(channel.connector_id))
    return _attach_channel_operator_state(channel, connector)


@router.put("/{channel_id}", response_model=Channel)
async def update_channel(
    channel_id: int,
    channel: ChannelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a channel.

    Args:
        channel_id: Identifier of the channel to update.
        channel: New channel values.
        db: Database session dependency.

    Returns:
        The updated channel instance.

    Raises:
        HTTPException: If the channel does not exist.
    """
    db_channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.connector_id is not None:
        connector = crud.connector.get(db, channel.connector_id)
        if not connector or connector.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
    updated = crud.channel.update(db, db_obj=db_channel, obj_in=channel)
    connector = crud.connector.get(db, int(updated.connector_id))
    return _attach_channel_operator_state(updated, connector)


@router.delete("/{channel_id}", response_model=Channel)
async def delete_channel(
    channel_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a channel.

    Args:
        channel_id: Identifier of the channel to delete.
        db: Database session dependency.

    Returns:
        The deleted channel instance.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        if force:
            db.query(ChannelRelay).filter(ChannelRelay.channel_id == channel_id).delete(
                synchronize_session=False
            )
            delete_channel_messages(db, channel_id)
            delete_channel_filters(db, channel_id)
            db.query(Action).filter(Action.reply_to == channel_id).delete(
                synchronize_session=False
            )
            db.commit()
        return crud.channel.remove(db, channel_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Channel has related records. Remove filters/messages first or retry with force=true.",
        )


@router.get("/{channel_id}/messages", response_model=List[ChannelMessageOut])
async def get_channel_messages(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _mark_stale_channel_relays(
        db, channel_id=channel_id, stale_after_seconds=_RELAY_DEFAULT_STALE_SECONDS
    )
    return get_channel_message_records(db, channel_id)


@router.get("/{channel_id}/relays", response_model=List[ChannelRelayOut])
async def get_channel_relays(
    channel_id: int,
    include_terminal: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    query = db.query(ChannelRelay).filter(ChannelRelay.channel_id == int(channel_id))
    if not include_terminal:
        query = query.filter(ChannelRelay.status.in_(sorted(_RELAY_OPEN_STATUSES)))
    return query.order_by(ChannelRelay.created_at.asc(), ChannelRelay.id.asc()).all()


@router.post("/{channel_id}/relays/sweep", response_model=ChannelRelaySweepResponse)
async def sweep_channel_relays(
    channel_id: int,
    stale_after_seconds: int = _RELAY_DEFAULT_STALE_SECONDS,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    relays = _mark_stale_channel_relays(
        db, channel_id=channel_id, stale_after_seconds=stale_after_seconds
    )
    return ChannelRelaySweepResponse(
        channel_id=int(channel_id), stale_count=len(relays), relays=relays
    )


@router.post("/{channel_id}/messages", response_model=ChannelMessageOut)
async def create_channel_message(
    channel_id: int,
    payload: ChannelMessageCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    connector = crud.connector.get(db, int(channel.connector_id))
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    await _deliver_channel_message(channel, connector, payload.content)
    record = create_channel_message_record(db, channel_id, payload, source="user")
    if _is_switchboard_party_line(channel) and not _is_party_line_relay_content(
        payload.content
    ):
        relay_id = uuid.uuid4().hex
        await _fanout_switchboard_party_line(
            db,
            user_id=int(current_user.id),
            channel=channel,
            source_connector=connector,
            source_message=record,
            content=payload.content,
            relay_id=relay_id,
            relay_callback_url=_relay_callback_url(
                request,
                channel_id=int(channel.id),
                source_message_id=int(record.id),
                relay_id=relay_id,
            ),
        )
    return record


@router.post("/{channel_id}/relay-callback", response_model=ChannelMessageOut)
async def create_channel_relay_callback(
    channel_id: int,
    payload: ChannelRelayCallback,
    relay_token: str = "",
    db: Session = Depends(get_db),
):
    channel = crud.channel.get(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not _verify_relay_callback_token(
        channel_id,
        int(payload.source_message_id),
        payload.relay_id,
        relay_token,
    ):
        raise HTTPException(status_code=401, detail="Invalid relay callback token")
    _relays, changed = _record_relay_callback(
        db, channel_id=channel_id, payload=payload
    )
    status_text = _normalize_relay_callback_status(payload.status, payload.success)
    existing = (
        None
        if changed
        else _latest_relay_callback_message(
            db,
            channel_id=channel_id,
            relay_id=payload.relay_id,
            status_text=status_text,
        )
    )
    if existing is not None:
        return existing
    return create_channel_message_record(
        db,
        channel_id,
        ChannelMessageCreate(content=_relay_callback_content(payload)),
        source="relay-callback",
    )


@router.post("/{channel_id}/operator", response_model=ChannelOperatorResponse)
async def set_channel_operator_mode(
    channel_id: int,
    payload: ChannelOperatorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    connector = crud.connector.get(db, int(channel.connector_id))
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")

    cfg = dict(connector.config or {})
    channel_states = dict(_channel_operator_modes(cfg))
    mode = _normalize_operator_mode(payload.mode, strict=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    note = str(payload.note or "").strip()
    channel_states[str(channel.id)] = {
        "mode": mode,
        "note": note,
        "updated_at": updated_at,
    }
    cfg["channel_operator_modes"] = channel_states
    connector.config = cfg
    db.add(connector)
    db.commit()
    db.refresh(connector)

    detail = (
        "channel manual mode active"
        if mode == "take"
        else "channel shared mode active"
        if mode == "co_pilot"
        else "channel auto mode active"
    )
    return ChannelOperatorResponse(
        channel_id=int(channel.id),
        connector_id=int(connector.id),
        operator_mode=mode,
        operator_note=note,
        operator_updated_at=updated_at,
        detail=detail,
    )


@router.post("/{channel_id}/feeds/start")
async def start_channel_feed(
    channel_id: int,
    payload: ChannelFeedStart,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return start_feed(channel_id, payload.dict())


@router.post("/{channel_id}/feeds/stop")
async def stop_channel_feed(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return stop_feed(channel_id)


@router.get("/{channel_id}/feeds/status")
async def channel_feed_status(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return feed_status(channel_id)
