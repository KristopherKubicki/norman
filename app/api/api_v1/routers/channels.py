"""API routes for :class:`~app.models.channel.Channel`."""

import asyncio
import inspect
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.crud.channel_message import create as create_channel_message_record
from app.crud.channel_message import get_by_channel as get_channel_message_records
from app.crud.channel_message import delete_by_channel as delete_channel_messages
from app.crud.channel_filter import delete_by_channel as delete_channel_filters
from app.models.action import Action
from app.api.deps import get_db, get_current_user
from app.connectors.connector_utils import get_connector
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
from app.services import estate_sync

router = APIRouter()
_OPERATOR_MODES = {"observe", "take", "co_pilot"}
_SUBPRIME_EXCLUDED_CONNECTORS = {"tmux:logs", "tmux:operator"}
_SUBPRIME_BROKER_SLUGS = {
    "norman",
    "norman-prime",
    "norman-service",
    "subprime",
    "switchboard",
}
_SUBPRIME_HOME_OPS_SLUGS = {"housebot", "glimpser", "autocamera"}
_SUBPRIME_SHARED_INFRA_SLUGS = {"networking", "uplink", "cloudagent"}
_SUBPRIME_WORK_SLUGS = {
    "earlybird",
    "infra",
    "control-plane",
    "market-sizing",
    "tmi-dashboards",
    "gold-book",
    "compere",
    "leadership-kpis",
    "panelbot",
    "scout",
    "publisher",
    "platinum-standard",
}
_SUBPRIME_BROKER_ONLY_SLUGS = {
    "castle",
    "theseus",
    "uscache",
    "phone-ops",
    "mls",
    "dj",
    "studio",
    "tv",
}
_SUBPRIME_PRIVATE_SLUGS = {
    "finance-reader",
    "health-reader",
    "parkergale",
    "parkergale-reader",
    "pefb",
    "private-home",
    "private-host",
}
_SUBPRIME_ALIAS_OVERRIDES = {
    "cp": "control-plane",
    "dashboards": "tmi-dashboards",
    "eyebat": "glimpser",
    "glimpse": "glimpser",
    "goldbook": "gold-book",
    "keystone": "compere",
    "kpis": "leadership-kpis",
    "market": "market-sizing",
    "mlsbot": "mls",
    "norman": "norman-service",
    "pef": "parkergale",
    "pefb": "parkergale",
    "phone": "phone-ops",
    "platinum": "platinum-standard",
    "switchboard": "norman-service",
}
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


def _is_subprime_party_line(channel) -> bool:
    key = _normalize_channel_key(getattr(channel, "name", ""))
    return key in {"console subprime", "subprime"}


def _normalize_subprime_slug(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^tmux[:\s-]*", "", text)
    text = text.replace("_", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return _SUBPRIME_ALIAS_OVERRIDES.get(text, text)


def _subprime_host_aliases(raw_url: str | None) -> list[str]:
    value = str(raw_url or "").strip()
    if not value:
        return []
    try:
        parts = urlsplit(value)
    except ValueError:
        return []
    host = (parts.hostname or "").strip().lower()
    if not host:
        return []
    labels = [label for label in host.split(".") if label]
    candidates = [host]
    if labels:
        candidates.append(labels[0])
    return [_normalize_subprime_slug(item) for item in candidates if item]


def _subprime_service_registry_records() -> list[dict[str, Any]]:
    try:
        registry = estate_sync.load_runtime_registry()
    except (
        Exception
    ):  # pragma: no cover - defensive fallback for malformed runtime state
        return []
    return list(registry.get("services") or [])


def _subprime_service_alias_map() -> dict[str, dict[str, Any]]:
    alias_map: dict[str, dict[str, Any]] = {}
    for service in _subprime_service_registry_records():
        aliases = {
            _normalize_subprime_slug(service.get("slug")),
            _normalize_subprime_slug(service.get("display_name")),
        }
        for url_field in (
            "console_url",
            "console_url_tailnet",
            "web_url",
            "web_url_tailnet",
        ):
            aliases.update(_subprime_host_aliases(service.get(url_field)))
        for alias in aliases:
            if alias:
                alias_map.setdefault(alias, service)
    return alias_map


def _connector_subprime_identity(connector) -> tuple[str, dict[str, Any] | None, bool]:
    cfg = dict(getattr(connector, "config", None) or {})
    candidates = [
        str(getattr(connector, "name", "") or ""),
        str(cfg.get("session") or ""),
        str(cfg.get("session_name") or ""),
    ]
    candidates.extend(
        _subprime_host_aliases(cfg.get("collector_url") or cfg.get("web_url") or "")
    )
    alias_map = _subprime_service_alias_map()
    normalized_candidates = [
        _normalize_subprime_slug(value)
        for value in candidates
        if str(value or "").strip()
    ]
    for candidate in normalized_candidates:
        record = alias_map.get(candidate)
        if record:
            return str(record.get("slug") or candidate), record, True
    for candidate in normalized_candidates:
        if (
            candidate in _SUBPRIME_BROKER_SLUGS
            or candidate in _SUBPRIME_HOME_OPS_SLUGS
            or candidate in _SUBPRIME_SHARED_INFRA_SLUGS
            or candidate in _SUBPRIME_WORK_SLUGS
            or candidate in _SUBPRIME_BROKER_ONLY_SLUGS
            or candidate in _SUBPRIME_PRIVATE_SLUGS
        ):
            return candidate, None, True
    return (normalized_candidates[0] if normalized_candidates else "", None, False)


def _subprime_lane_for_identity(slug: str, record: dict[str, Any] | None) -> str:
    canonical = _normalize_subprime_slug(slug)
    if canonical in _SUBPRIME_BROKER_SLUGS:
        return "broker"
    if canonical in _SUBPRIME_PRIVATE_SLUGS:
        return "private"
    if canonical in _SUBPRIME_HOME_OPS_SLUGS:
        return "home-ops"
    if canonical in _SUBPRIME_SHARED_INFRA_SLUGS:
        return "shared-infra"
    if canonical in _SUBPRIME_BROKER_ONLY_SLUGS:
        return "broker-only"
    if canonical in _SUBPRIME_WORK_SLUGS:
        return "work"
    if record:
        principal = _normalize_subprime_slug(record.get("principal"))
        domain = _normalize_subprime_slug(record.get("domain"))
        worker = _normalize_subprime_slug(record.get("worker"))
        if principal == "parkergale":
            return "private"
        if domain in {"kristopher-finance", "kristopher-health", "parkergale-private"}:
            return "private"
        if worker == "private-host":
            return "private"
        if principal == "openbrand":
            return "work"
    return "broker-only"


def _subprime_allowed_target_lanes(source_lane: str) -> set[str]:
    if source_lane == "broker":
        return {"broker", "home-ops", "shared-infra", "work", "broker-only"}
    if source_lane == "private":
        return {"broker"}
    if source_lane == "home-ops":
        return {"broker", "home-ops"}
    if source_lane == "shared-infra":
        return {"broker", "shared-infra"}
    if source_lane == "work":
        return {"broker", "work"}
    return {"broker"}


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

    body = urlencode({"message": text}).encode("utf-8")
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
        detail = "Remote console rejected the Subprime broadcast."
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


async def _send_connector_message(connector, payload: Any) -> None:
    if str(
        getattr(connector, "connector_type", "") or ""
    ).strip().lower() == "tmux" and _connector_collector_url(connector):
        await _send_tmux_collector_message(connector, payload)
        return
    instance = get_connector(connector.connector_type, connector.config or {})
    result = instance.send_message(payload)
    if asyncio.iscoroutine(result):
        await result


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


def _subprime_party_line_targets(db: Session, user_id: int, source_connector_id: int):
    source_connector = crud.connector.get(db, source_connector_id)
    if not source_connector:
        return []
    source_slug, source_record, source_recognized = _connector_subprime_identity(
        source_connector
    )
    source_lane = _subprime_lane_for_identity(source_slug, source_record)
    allowed_lanes = _subprime_allowed_target_lanes(source_lane)
    targets = []
    for connector in crud.connector.get_multi_by_user(db, user_id):
        if int(connector.id) == int(source_connector_id):
            continue
        if str(connector.connector_type or "").strip().lower() != "tmux":
            continue
        name_key = str(connector.name or "").strip().lower()
        if name_key in _SUBPRIME_EXCLUDED_CONNECTORS:
            continue
        target_slug, target_record, target_recognized = _connector_subprime_identity(
            connector
        )
        target_lane = _subprime_lane_for_identity(target_slug, target_record)
        if not target_recognized and target_lane != "broker":
            continue
        if not source_recognized and target_lane != "broker":
            continue
        if target_lane not in allowed_lanes:
            continue
        targets.append(connector)
    return targets


async def _fanout_subprime_party_line(
    db: Session,
    *,
    user_id: int,
    channel,
    source_connector,
    content: str,
) -> None:
    targets = _subprime_party_line_targets(db, user_id, int(source_connector.id))
    if not targets:
        return

    payload = {
        "text": (
            "[Norman Subprime party line]\n"
            "Passive fleet context only. Absorb this silently unless you are directly addressed or explicitly asked to act.\n\n"
            f"{content.strip()}"
        ),
        "channel_id": int(channel.id),
        "channel_name": channel.name,
        "submit_mode": "tab_enter",
        "enter_count": 1,
    }

    failures: list[str] = []
    delivered = 0
    for connector in targets:
        try:
            await _send_connector_message(connector, payload)
            delivered += 1
        except Exception as exc:  # pragma: no cover - defensive logging path
            failures.append(f"{connector.name}: {exc}")

    logger.info(
        "Subprime party line fanout attempted",
        extra={
            "channel": str(channel.name or ""),
            "source_connector": str(source_connector.name or source_connector.id),
            "delivered": delivered,
            "failed": len(failures),
        },
    )
    if failures:
        logger.warning("Subprime party line fanout failures: %s", "; ".join(failures))


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
    return get_channel_message_records(db, channel_id)


@router.post("/{channel_id}/messages", response_model=ChannelMessageOut)
async def create_channel_message(
    channel_id: int,
    payload: ChannelMessageCreate,
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
    if _is_subprime_party_line(channel):
        await _fanout_subprime_party_line(
            db,
            user_id=int(current_user.id),
            channel=channel,
            source_connector=connector,
            content=payload.content,
        )
    return create_channel_message_record(db, channel_id, payload, source="user")


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
