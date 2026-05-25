import asyncio
import json
import pathlib
import re
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import crud
from app.api.deps import get_current_user, get_db
from app.connectors.connector_utils import get_connector
from app.core.command_policy import evaluate_tmux_payload
from app.core.config import get_settings
from app.core.safety_controls import tmux_commands_block_reason
from app.models import Bot, Channel, Connector, User
from app.schemas.bot import BotCreate
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate
from app.services import tmux_inspector

router = APIRouter(prefix="/tmux", tags=["tmux"])

_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DEFAULT_PROTECTED_SESSIONS = {"norman-web", "operator", "norman-agent"}
_OPERATOR_MODES = {"observe", "take", "co_pilot"}


class TmuxSendRequest(BaseModel):
    connector_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1, max_length=12000)
    target: str = Field("", max_length=128)
    socket_path: str = Field("", max_length=512)
    enter_count: int = Field(2, ge=1, le=8)


class TmuxSendResponse(BaseModel):
    status: str
    reason: str = ""
    target: str = ""
    submit_mode: str = ""
    approval_id: int | None = None
    confirm_token: str = ""


class TmuxControlSessionOut(BaseModel):
    session_name: str
    windows: int = 0
    attached: int = 0
    target: str = ""
    pane_current_command: str = ""
    pane_current_path: str = ""
    managed: bool = False
    connector_id: int | None = None
    connector_name: str = ""
    protected: bool = False
    protected_reason: str = ""
    locked: bool = False
    operator_mode: str = "observe"
    operator_note: str = ""
    operator_updated_at: str = ""
    web_url: str = ""
    status_available: bool = False
    status_message: str = ""
    auth_required: bool = False
    auth_mode: str = ""
    auth_summary: str = ""
    auth_verification_url: str = ""
    auth_device_code: str = ""


class TmuxControlSessionsResponse(BaseModel):
    items: list[TmuxControlSessionOut]
    count: int


class TmuxControlOpsItemOut(BaseModel):
    session_name: str
    running: bool = False
    windows: int = 0
    attached: int = 0
    target: str = ""
    pane_current_command: str = ""
    pane_current_path: str = ""
    managed: bool = False
    connector_id: int | None = None
    connector_name: str = ""
    protected: bool = False
    protected_reason: str = ""
    locked: bool = False
    operator_mode: str = "observe"
    operator_note: str = ""
    operator_updated_at: str = ""
    web_url: str = ""
    status_available: bool = False
    pending: bool = False
    has_response: bool = False
    needs_turn: bool = False
    status_message: str = ""
    last_action: str = ""
    last_action_at: int = 0
    last_action_detail: str = ""
    last_finished_at: int = 0
    prompt_preview: str = ""
    response_preview: str = ""
    state: str = "idle"
    state_label: str = "Idle"
    state_detail: str = ""
    auth_required: bool = False
    auth_mode: str = ""
    auth_summary: str = ""
    auth_verification_url: str = ""
    auth_device_code: str = ""


class TmuxControlOpsResponse(BaseModel):
    items: list[TmuxControlOpsItemOut]
    count: int
    running: int = 0
    working: int = 0
    needs_turn: int = 0
    locked: int = 0
    stopped: int = 0


class TmuxAdoptRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=128)
    socket_path: str = Field("", max_length=512)
    connector_name: str = Field("", max_length=128)
    channel_name: str = Field("", max_length=128)
    create_channel: bool = True
    create_bot: bool = False
    bot_name: str = Field("", max_length=128)
    protected: bool = False
    working_dir: str = Field("", max_length=1024)
    bootstrap_command: str = Field("", max_length=12000)


class TmuxAdoptAllRequest(BaseModel):
    socket_path: str = Field("", max_length=512)
    include_protected: bool = False
    create_channels: bool = True
    create_bots: bool = False


class TmuxAdoptResponse(BaseModel):
    status: str
    session: str
    connector_id: int
    connector_name: str
    channel_id: int | None = None
    channel_name: str = ""
    bot_id: int | None = None
    bot_name: str = ""
    protected: bool = False
    target: str = ""


class TmuxAdoptAllResponse(BaseModel):
    status: str
    adopted: int
    skipped: int
    items: list[TmuxAdoptResponse]


class TmuxSessionStartRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)
    socket_path: str = Field("", max_length=512)
    target: str = Field("", max_length=128)
    working_dir: str = Field("", max_length=1024)
    bootstrap_command: str = Field("", max_length=12000)
    force_restart: bool = False


class TmuxSessionStopRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)
    socket_path: str = Field("", max_length=512)
    force: bool = False


class TmuxSessionLockRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)
    socket_path: str = Field("", max_length=512)
    locked: bool = True
    stop_session: bool = False
    force: bool = False


class TmuxSessionOperatorRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)
    mode: str = Field("observe", max_length=32)
    note: str = Field("", max_length=280)


class TmuxSessionWebUrlRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)
    web_url: str = Field("", max_length=2048)


class TmuxSessionAuthRequest(BaseModel):
    session: str = Field("", max_length=128)
    connector_id: int | None = Field(None, ge=1)


class TmuxSessionActionResponse(BaseModel):
    status: str
    session: str
    target: str = ""
    detail: str = ""
    started_session: bool = False
    stopped_session: bool = False
    launched_command: bool = False
    protected: bool = False
    locked: bool = False
    operator_mode: str = "observe"
    operator_note: str = ""
    operator_updated_at: str = ""
    web_url: str = ""
    auth_required: bool = False
    auth_mode: str = ""
    auth_summary: str = ""
    auth_verification_url: str = ""
    auth_device_code: str = ""


class TmuxLockAllRequest(BaseModel):
    locked: bool = True
    stop_sessions: bool = False
    include_protected: bool = False
    force: bool = False
    socket_path: str = Field("", max_length=512)


class TmuxLockAllResponse(BaseModel):
    status: str
    locked: bool
    updated: int
    stopped_sessions: int
    skipped_protected: int


class TmuxProfileSummary(BaseModel):
    name: str
    updated_at: str


class TmuxProfileListResponse(BaseModel):
    items: list[TmuxProfileSummary]
    count: int


class TmuxProfileSaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    running_only: bool = False
    include_protected: bool = False
    socket_path: str = Field("", max_length=512)


class TmuxProfileLoadRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    start_sessions: bool = True
    force_restart: bool = False
    include_protected: bool = False


class TmuxProfileRenameRequest(BaseModel):
    from_name: str = Field(..., min_length=1, max_length=64)
    to_name: str = Field(..., min_length=1, max_length=64)
    overwrite: bool = False


class TmuxProfileActionResponse(BaseModel):
    status: str
    name: str
    sessions: int
    applied: int


def _normalize_session_name(value: str) -> str:
    session = str(value or "").strip()
    if not session or not _SESSION_NAME_RE.match(session):
        raise HTTPException(status_code=400, detail="Invalid tmux session name")
    return session


def _protected_sessions() -> set[str]:
    configured = str(
        getattr(get_settings(), "tmux_protected_sessions", "") or ""
    ).strip()
    if not configured:
        return set(_DEFAULT_PROTECTED_SESSIONS)
    entries = {
        item.strip()
        for item in configured.split(",")
        if item and item.strip() and _SESSION_NAME_RE.match(item.strip())
    }
    if not entries:
        return set(_DEFAULT_PROTECTED_SESSIONS)
    return entries


def _connector_map_by_session(db: Session, user: User) -> Dict[str, Connector]:
    mapping: Dict[str, Connector] = {}
    rows = (
        db.query(Connector)
        .filter(Connector.user_id == user.id, Connector.connector_type == "tmux")
        .order_by(Connector.id.asc())
        .all()
    )
    for row in rows:
        config = dict(row.config or {})
        session_name = str(config.get("session") or "").strip()
        if not session_name and row.name and str(row.name).startswith("tmux:"):
            session_name = str(row.name).split(":", 1)[1].strip()
        if session_name and session_name not in mapping:
            mapping[session_name] = row
    return mapping


def _normalize_operator_mode(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text not in _OPERATOR_MODES:
        return "observe"
    return text


def _is_protected_session(
    session: str, connector: Optional[Connector] = None
) -> tuple[bool, str]:
    if session in _protected_sessions():
        return True, "system"
    if connector:
        cfg = dict(connector.config or {})
        if bool(cfg.get("protected")):
            return True, "connector"
    return False, ""


def _is_locked_session(connector: Optional[Connector]) -> bool:
    if connector is None:
        return False
    cfg = dict(connector.config or {})
    return bool(cfg.get("locked"))


def _operator_mode(connector: Optional[Connector]) -> str:
    if not connector:
        return "observe"
    cfg = dict(connector.config or {})
    return _normalize_operator_mode(cfg.get("operator_mode"))


def _operator_note(connector: Optional[Connector]) -> str:
    if not connector:
        return ""
    cfg = dict(connector.config or {})
    return str(cfg.get("operator_note") or "").strip()


def _operator_updated_at(connector: Optional[Connector]) -> str:
    if not connector:
        return ""
    cfg = dict(connector.config or {})
    return str(cfg.get("operator_updated_at") or "").strip()


def _web_url(connector: Optional[Connector]) -> str:
    if not connector:
        return ""
    cfg = dict(connector.config or {})
    return str(cfg.get("web_url") or "").strip()


def _normalize_web_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    scheme = str(parts.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Web URL must use http or https.")
    if not str(parts.netloc or "").strip():
        raise HTTPException(status_code=400, detail="Web URL is missing a host.")
    return urlunsplit(
        (
            scheme,
            parts.netloc,
            parts.path or "",
            parts.query or "",
            parts.fragment or "",
        )
    )


def _preview_console_text(value: str, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if not text or text in {"[no prompt yet]", "[no response yet]"}:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _console_auth_state(payload: dict[str, Any]) -> dict[str, Any]:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return {
            "auth_required": False,
            "auth_mode": "",
            "auth_summary": "",
            "auth_verification_url": "",
            "auth_device_code": "",
        }
    return {
        "auth_required": bool(auth.get("required")),
        "auth_mode": str(auth.get("mode") or "").strip(),
        "auth_summary": str(auth.get("summary") or "").strip(),
        "auth_verification_url": str(auth.get("verification_url") or "").strip(),
        "auth_device_code": str(auth.get("device_code") or "").strip(),
    }


def _control_session_records(
    db: Session,
    user: User,
    *,
    socket_path: str = "",
    include_stopped: bool = False,
) -> list[dict[str, Any]]:
    sessions = tmux_inspector.list_sessions(socket_path=socket_path)
    panes = tmux_inspector.list_panes(socket_path=socket_path)
    connector_map = _connector_map_by_session(db, user)
    session_map = {
        str(item.get("session_name") or "").strip(): item
        for item in sessions
        if str(item.get("session_name") or "").strip()
    }
    session_names = set(session_map)
    if include_stopped:
        session_names.update(connector_map)

    records: list[dict[str, Any]] = []
    for session_name in sorted(session_names, key=lambda value: value.lower()):
        connector = connector_map.get(session_name)
        session_item = session_map.get(session_name, {})
        primary = (
            _find_primary_session_pane(panes, session_name)
            if session_name in session_map
            else {}
        )
        protected, reason = _is_protected_session(session_name, connector)
        records.append(
            {
                "session_name": session_name,
                "running": session_name in session_map,
                "windows": int(session_item.get("windows") or 0),
                "attached": int(session_item.get("attached") or 0),
                "target": str(primary.get("target") or ""),
                "pane_current_command": str(primary.get("pane_current_command") or ""),
                "pane_current_path": str(primary.get("pane_current_path") or ""),
                "managed": connector is not None,
                "connector_id": int(connector.id) if connector else None,
                "connector_name": str(connector.name or "") if connector else "",
                "protected": protected,
                "protected_reason": reason,
                "locked": _is_locked_session(connector),
                "operator_mode": _operator_mode(connector),
                "operator_note": _operator_note(connector),
                "operator_updated_at": _operator_updated_at(connector),
                "web_url": _web_url(connector),
            }
        )
    return records


def _console_status_url(web_url: str) -> str:
    normalized = str(web_url or "").strip()
    if not normalized:
        return ""
    try:
        parts = urlsplit(_normalize_web_url(normalized))
    except HTTPException:
        return ""
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    status_query = {}
    token = str(query_items.get("token") or "").strip()
    if token:
        status_query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/api/status",
            urlencode(status_query),
            "",
        )
    )


def _console_action_url(web_url: str, action_path: str) -> str:
    normalized = str(web_url or "").strip()
    if not normalized:
        return ""
    try:
        parts = urlsplit(_normalize_web_url(normalized))
    except HTTPException:
        return ""
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    action_query = {}
    token = str(query_items.get("token") or "").strip()
    if token:
        action_query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            action_path,
            urlencode(action_query),
            "",
        )
    )


def _fetch_console_status(web_url: str, *, timeout: float = 1.75) -> dict[str, Any]:
    snapshot = {
        "reachable": False,
        "pending": False,
        "has_response": False,
        "status_message": "",
        "last_action": "",
        "last_action_at": 0,
        "last_action_detail": "",
        "last_finished_at": 0,
        "prompt_preview": "",
        "response_preview": "",
        "auth_required": False,
        "auth_mode": "",
        "auth_summary": "",
        "auth_verification_url": "",
        "auth_device_code": "",
    }
    status_url = _console_status_url(web_url)
    if not status_url:
        return snapshot
    request = Request(
        status_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NormanPrime/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return snapshot
    if not isinstance(payload, dict):
        return snapshot

    last_prompt = str(payload.get("last_prompt") or "").strip()
    last_response = str(payload.get("last_response") or "").strip()
    has_response = bool(last_response and last_response != "[no response yet]")
    try:
        last_action_at = int(payload.get("last_action_at") or 0)
    except (TypeError, ValueError):
        last_action_at = 0
    try:
        last_finished_at = int(payload.get("last_finished_at") or 0)
    except (TypeError, ValueError):
        last_finished_at = 0

    snapshot.update(
        {
            "reachable": True,
            "pending": bool(payload.get("pending")),
            "has_response": has_response,
            "status_message": str(payload.get("status_message") or "").strip(),
            "last_action": str(payload.get("last_action") or "").strip(),
            "last_action_at": last_action_at,
            "last_action_detail": str(payload.get("last_action_detail") or "").strip(),
            "last_finished_at": last_finished_at,
            "prompt_preview": _preview_console_text(last_prompt),
            "response_preview": _preview_console_text(last_response),
            **_console_auth_state(payload),
        }
    )
    return snapshot


def _post_console_action(
    web_url: str, action_path: str, *, timeout: float = 8.0
) -> dict[str, Any]:
    action_url = _console_action_url(web_url, action_path)
    if not action_url:
        raise HTTPException(
            status_code=400, detail="Session is missing a valid web link."
        )
    request = Request(
        action_url,
        data=b"",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "NormanPrime/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = "Remote console rejected the auth action."
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(payload, dict):
                detail = str(payload.get("error") or detail)
        except (ValueError, json.JSONDecodeError):
            pass
        raise HTTPException(status_code=502, detail=detail) from exc
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502, detail="Remote console auth action failed."
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502, detail="Remote console returned an invalid response."
        )
    return payload


async def _fetch_console_status_map(web_urls: list[str]) -> dict[str, dict[str, Any]]:
    unique_urls = list(dict.fromkeys(url for url in web_urls if str(url or "").strip()))
    if not unique_urls:
        return {}
    results = await asyncio.gather(
        *[asyncio.to_thread(_fetch_console_status, url) for url in unique_urls],
        return_exceptions=True,
    )
    mapping: dict[str, dict[str, Any]] = {}
    for url, result in zip(unique_urls, results, strict=False):
        if isinstance(result, Exception):
            mapping[url] = _fetch_console_status("")
            continue
        mapping[url] = result
    return mapping


def _derive_ops_state(
    record: dict[str, Any], status: dict[str, Any]
) -> tuple[str, str, str]:
    if bool(record.get("locked")):
        return ("locked", "Locked", "Failsafe lock is active.")
    if not bool(record.get("running")):
        return ("stopped", "Stopped", "Session is not currently running.")
    if bool(status.get("pending")):
        detail = str(status.get("status_message") or "").strip()
        return ("working", "Working", detail or "Prompt is still running.")
    if bool(status.get("reachable")) and bool(status.get("has_response")):
        detail = str(status.get("status_message") or "").strip()
        if detail.lower() in {"ready.", "web prompt completed."}:
            detail = "Latest reply is ready for another turn."
        return (
            "needs_turn",
            "Needs turn",
            detail or "Latest reply is ready for another turn.",
        )

    operator_mode = str(record.get("operator_mode") or "observe").strip().lower()
    if operator_mode == "take":
        return ("manual", "Manual", "Operator takeover is active.")
    if operator_mode == "co_pilot":
        return ("shared", "Shared", "Co-pilot mode is active.")
    if bool(status.get("reachable")):
        detail = str(status.get("last_action_detail") or "").strip()
        return ("ready", "Ready", detail or "Session is live and waiting.")
    return ("live", "Live", "Managed session is running.")


def _maybe_watchdog_autolock(db: Session, connector: Optional[Connector]) -> bool:
    """Auto-lock a managed tmux connector when its expected session vanishes."""
    if connector is None:
        return False

    app_settings = get_settings()
    if not bool(getattr(app_settings, "safety_tmux_watchdog_autolock", False)):
        return False

    cfg = dict(connector.config or {})
    if bool(cfg.get("locked")):
        return False
    if cfg.get("watchdog_enabled") is False:
        return False

    session_name = _connector_session_name(connector)
    if not session_name:
        return False
    socket_path = str(cfg.get("socket_path") or "").strip()
    try:
        running = _tmux_has_session(session_name, socket_path=socket_path)
    except Exception:
        # If tmux is unavailable, avoid mutating lock state.
        return False
    if running:
        return False

    cfg["locked"] = True
    cfg["locked_reason"] = "watchdog:session_missing"
    connector.config = cfg
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return True


def _read_session_bootstrap_from_dir(working_dir: str) -> str:
    raw_working_dir = str(working_dir or "").strip()
    if not raw_working_dir:
        return ""
    base = pathlib.Path(raw_working_dir)
    session_file = base / ".session"
    if not session_file.exists():
        return ""
    try:
        lines = [
            line.strip()
            for line in session_file.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
        ]
    except OSError:
        return ""
    lines = [line for line in lines if line]
    return lines[-1] if lines else ""


def _run_tmux(
    *args: str, socket_path: str = "", check: bool = False
) -> subprocess.CompletedProcess:
    return tmux_inspector._run_tmux(*args, socket_path=socket_path, check=check)


def _tmux_has_session(session: str, socket_path: str = "") -> bool:
    proc = _run_tmux("has-session", "-t", session, socket_path=socket_path, check=False)
    return proc.returncode == 0


def _tmux_target_exists(target: str, socket_path: str = "") -> bool:
    proc = _run_tmux(
        "display-message",
        "-p",
        "-t",
        target,
        "#{pane_id}",
        socket_path=socket_path,
        check=False,
    )
    return proc.returncode == 0


def _pane_child_command(target: str, socket_path: str = "") -> str:
    proc = _run_tmux(
        "display-message",
        "-p",
        "-t",
        target,
        "#{pane_pid}",
        socket_path=socket_path,
        check=False,
    )
    pid = str(proc.stdout or "").strip()
    if not pid.isdigit():
        return ""
    ps_proc = subprocess.run(
        ["ps", "-o", "cmd=", "--ppid", pid],
        capture_output=True,
        text=True,
        check=False,
    )
    if ps_proc.returncode != 0:
        return ""
    lines = [
        line.strip() for line in (ps_proc.stdout or "").splitlines() if line.strip()
    ]
    return lines[0] if lines else ""


def _command_matches_running(child_cmd: str, expected_cmd: str) -> bool:
    child = " ".join(str(child_cmd or "").split()).lower()
    expected = " ".join(str(expected_cmd or "").split()).lower()
    if not child or not expected:
        return False
    return expected in child


def _launch_command(
    target: str, command: str, working_dir: str = "", socket_path: str = ""
) -> None:
    _run_tmux("send-keys", "-t", target, "C-c", socket_path=socket_path, check=False)
    launch_line = str(command or "").strip()
    if working_dir:
        launch_line = f"cd {shlex.quote(working_dir)} && {launch_line}"
    _run_tmux(
        "send-keys",
        "-t",
        target,
        "-l",
        launch_line,
        socket_path=socket_path,
        check=True,
    )
    _run_tmux("send-keys", "-t", target, "C-m", socket_path=socket_path, check=True)


def _unique_channel_name(db: Session, base: str) -> str:
    candidate = str(base or "").strip() or "Console"
    if db.query(Channel.id).filter(Channel.name == candidate).first() is None:
        return candidate
    idx = 2
    while True:
        next_name = f"{candidate} ({idx})"
        if db.query(Channel.id).filter(Channel.name == next_name).first() is None:
            return next_name
        idx += 1


def _connector_session_name(connector: Connector) -> str:
    cfg = dict(connector.config or {})
    session_name = str(cfg.get("session") or "").strip()
    if session_name:
        return session_name
    name = str(connector.name or "").strip()
    if name.startswith("tmux:"):
        return name.split(":", 1)[1].strip()
    return ""


def _find_primary_session_pane(panes: list[dict], session_name: str) -> dict:
    session_panes = [
        p for p in panes if str(p.get("session_name") or "") == session_name
    ]
    if not session_panes:
        return {}
    preferred = [
        p
        for p in session_panes
        if int(p.get("window_index") or 0) == 0 and int(p.get("pane_index") or 0) == 0
    ]
    return preferred[0] if preferred else session_panes[0]


def _ensure_tmux_session_running(
    *,
    session: str,
    target: str,
    working_dir: str,
    bootstrap_command: str,
    socket_path: str = "",
    force_restart: bool = False,
) -> tuple[bool, bool, str]:
    started_session = False
    launched_command = False
    if not _tmux_has_session(session, socket_path=socket_path):
        args = ["new-session", "-d", "-s", session]
        if working_dir:
            args.extend(["-c", working_dir])
        _run_tmux(*args, socket_path=socket_path, check=True)
        started_session = True

    resolved_target = str(target or "").strip() or f"{session}:0.0"
    if not _tmux_target_exists(resolved_target, socket_path=socket_path):
        resolved_target = f"{session}:0.0"

    bootstrap = str(bootstrap_command or "").strip()
    if bootstrap:
        running = _pane_child_command(resolved_target, socket_path=socket_path)
        if force_restart or not _command_matches_running(running, bootstrap):
            _launch_command(
                resolved_target,
                bootstrap,
                working_dir=working_dir,
                socket_path=socket_path,
            )
            launched_command = True

    return started_session, launched_command, resolved_target


def _resolve_control_session(
    *,
    db: Session,
    user: User,
    session: str = "",
    connector_id: Optional[int] = None,
) -> tuple[str, Optional[Connector]]:
    connector: Optional[Connector] = None
    session_name = str(session or "").strip()

    if connector_id:
        connector = crud.connector.get(db, int(connector_id))
        if not connector or connector.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
        if connector.connector_type != "tmux":
            raise HTTPException(status_code=400, detail="Connector is not tmux")
        session_name = session_name or _connector_session_name(connector)
    elif session_name:
        connector = _connector_map_by_session(db, user).get(session_name)

    session_name = _normalize_session_name(session_name)
    return session_name, connector


def _upsert_connector_for_session(
    *,
    db: Session,
    user: User,
    session: str,
    connector_name: str,
    target: str,
    working_dir: str,
    bootstrap_command: str,
    protected: bool,
) -> Connector:
    existing = _connector_map_by_session(db, user).get(session)
    cfg_updates = {
        "session": session,
        "target": target,
        "working_dir": working_dir,
        "session_bootstrap": bootstrap_command,
        "protected": bool(protected),
        "mode": "chat",
        "send_enter": True,
        "send_enter_count": 2,
        "policy": {"mode": "chat", "max_length": 8000},
    }

    if existing:
        cfg = dict(existing.config or {})
        dirty = False
        for key, value in cfg_updates.items():
            if value and cfg.get(key) != value:
                cfg[key] = value
                dirty = True
            if key == "protected" and cfg.get(key) != value:
                cfg[key] = value
                dirty = True
        if connector_name and existing.name != connector_name:
            existing.name = connector_name
            dirty = True
        if dirty:
            existing.config = cfg
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    created = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name=connector_name,
            connector_type="tmux",
            config=cfg_updates,
        ),
        user_id=user.id,
    )
    return created


def _ensure_channel_for_connector(
    *,
    db: Session,
    connector: Connector,
    requested_name: str,
    session: str,
) -> Optional[Channel]:
    existing = (
        db.query(Channel)
        .filter(Channel.connector_id == connector.id)
        .order_by(Channel.id.asc())
        .first()
    )
    if existing:
        return existing

    base = str(requested_name or "").strip() or f"Console - {session}"
    unique = _unique_channel_name(db, base)
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name=unique, connector_id=int(connector.id)),
    )
    return channel


def _ensure_bot_for_session(
    *,
    db: Session,
    user: User,
    session: str,
    requested_name: str,
) -> Optional[Bot]:
    existing = (
        db.query(Bot)
        .filter(Bot.user_id == user.id, Bot.session_id == session)
        .order_by(Bot.id.asc())
        .first()
    )
    if existing:
        return existing

    bot = crud.bot.create_bot(
        db,
        bot_create=BotCreate(
            name=(str(requested_name or "").strip() or f"Agent - {session}"),
            description=f"Managed tmux session {session}",
            session_id=session,
        ),
        user_id=user.id,
    )
    return bot


_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _normalize_profile_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or not _PROFILE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid profile name")
    return name


def _profile_dir_for_user(user: User) -> pathlib.Path:
    base = pathlib.Path("db") / "tmux_profiles" / str(int(user.id))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _profile_path(user: User, profile_name: str) -> pathlib.Path:
    return _profile_dir_for_user(user) / f"{_normalize_profile_name(profile_name)}.json"


def _profile_session_count(path: pathlib.Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    items = data.get("items") if isinstance(data, dict) else None
    return len(items) if isinstance(items, list) else 0


def _session_profile_payload(
    db: Session,
    user: User,
    *,
    running_only: bool = False,
    include_protected: bool = True,
    socket_path: str = "",
) -> dict:
    items = []
    connector_map = _connector_map_by_session(db, user)

    if running_only:
        panes = tmux_inspector.list_panes(socket_path=socket_path)
        sessions = tmux_inspector.list_sessions(socket_path=socket_path)
        for item in sessions:
            session = str(item.get("session_name") or "").strip()
            if not session or not _SESSION_NAME_RE.match(session):
                continue
            connector = connector_map.get(session)
            protected, _ = _is_protected_session(session, connector)
            if protected and not include_protected:
                continue
            cfg = dict(connector.config or {}) if connector else {}
            primary = _find_primary_session_pane(panes, session)
            target = str(primary.get("target") or cfg.get("target") or f"{session}:0.0")
            working_dir = str(
                primary.get("pane_current_path") or cfg.get("working_dir") or ""
            ).strip()
            bootstrap = str(cfg.get("session_bootstrap") or "").strip()
            if not bootstrap and working_dir:
                bootstrap = _read_session_bootstrap_from_dir(working_dir)
            items.append(
                {
                    "session": session,
                    "connector_name": str(
                        (connector.name if connector else "") or f"tmux:{session}"
                    ),
                    "target": target,
                    "working_dir": working_dir,
                    "session_bootstrap": bootstrap,
                    "web_url": _web_url(connector),
                    "protected": protected,
                }
            )
    else:
        for session, connector in connector_map.items():
            protected, _ = _is_protected_session(session, connector)
            if protected and not include_protected:
                continue
            cfg = dict(connector.config or {})
            items.append(
                {
                    "session": session,
                    "connector_name": connector.name,
                    "target": str(cfg.get("target") or f"{session}:0.0"),
                    "working_dir": str(cfg.get("working_dir") or ""),
                    "session_bootstrap": str(cfg.get("session_bootstrap") or ""),
                    "web_url": str(cfg.get("web_url") or ""),
                    "protected": protected,
                }
            )
    return {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_mode": "running" if running_only else "managed",
        "items": items,
    }


def _normalize_tmux_runtime_error(error: Exception) -> str:
    detail = str(error or "").strip()
    lowered = detail.lower()
    if "error connecting to" in lowered and "no such file or directory" in lowered:
        return (
            f"{detail}. tmux socket not found; ensure tmux is running and set the"
            " connector socket_path if using a non-default socket."
        )
    if "no server running" in lowered:
        return (
            f"{detail}. Start a tmux server for this user or set connector socket_path."
        )
    if "can't find pane" in lowered or "can't find window" in lowered:
        return (
            f"{detail}. Target pane is stale; refresh pane list and remap this stream."
        )
    return detail or "tmux operation failed"


@router.get("/sessions")
async def list_tmux_sessions(
    response: Response,
    socket_path: str = Query("", max_length=512),
    _current_user=Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, max-age=2, stale-while-revalidate=5"
    items = tmux_inspector.list_sessions(socket_path=socket_path)
    return {"items": items, "count": len(items)}


@router.get("/panes")
async def list_tmux_panes(
    response: Response,
    session: str = Query("", max_length=128),
    socket_path: str = Query("", max_length=512),
    _current_user=Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, max-age=2, stale-while-revalidate=5"
    items = tmux_inspector.list_panes(socket_path=socket_path)
    if session:
        items = [p for p in items if p.get("session_name") == session]
    return {"items": items, "count": len(items)}


@router.get("/capture")
async def capture_tmux_pane(
    target: str = Query(..., min_length=1, max_length=128),
    lines: int = Query(200, ge=10, le=2000),
    socket_path: str = Query("", max_length=512),
    _current_user=Depends(get_current_user),
):
    try:
        text = tmux_inspector.capture_pane(
            target=target, lines=lines, socket_path=socket_path
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))
    return {"target": target, "lines": lines, "text": text}


@router.post("/send", response_model=TmuxSendResponse)
async def send_tmux_message(
    payload: TmuxSendRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connector = crud.connector.get(db, payload.connector_id)
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector.connector_type != "tmux":
        raise HTTPException(status_code=400, detail="Connector is not tmux")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is empty")

    config = dict(connector.config or {})
    target = (payload.target or "").strip()
    socket_path = (payload.socket_path or "").strip()
    if target:
        config["target"] = target
    if socket_path:
        config["socket_path"] = socket_path
    if _is_locked_session(connector):
        resolved_target = str(config.get("target") or "")
        if not resolved_target and config.get("session"):
            resolved_target = f"{config.get('session')}:0.0"
        return TmuxSendResponse(
            status="blocked",
            reason="Session is locked by failsafe policy",
            target=resolved_target,
        )

    if _maybe_watchdog_autolock(db, connector):
        config = dict(connector.config or {})
        resolved_target = str(config.get("target") or "")
        if not resolved_target and config.get("session"):
            resolved_target = f"{config.get('session')}:0.0"
        return TmuxSendResponse(
            status="blocked",
            reason="Session auto-locked by watchdog (session missing)",
            target=resolved_target,
        )

    app_settings = get_settings()
    tmux_hold_reason = tmux_commands_block_reason(app_settings)
    if tmux_hold_reason:
        resolved_target = str(config.get("target") or "")
        if not resolved_target and config.get("session"):
            resolved_target = f"{config.get('session')}:0.0"
        return TmuxSendResponse(
            status="blocked",
            reason=tmux_hold_reason,
            target=resolved_target,
        )

    policy = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    mode = (
        str(
            config.get("mode")
            or policy.get("mode")
            or app_settings.safety_default_tmux_mode
            or "chat"
        )
        .strip()
        .lower()
    )
    allow_meta = bool(
        config.get(
            "allow_shell_metachar",
            policy.get("allow_shell_metachar", False),
        )
    )
    decision = evaluate_tmux_payload(
        text,
        mode=mode,
        allow_shell_metachar=allow_meta,
        profile=policy,
    )

    if decision.decision == "blocked":
        return TmuxSendResponse(
            status="blocked",
            reason=decision.reason,
        )

    execution_blocked = (
        not getattr(app_settings, "safety_execution_enabled", True)
    ) or getattr(app_settings, "safety_read_only", False)
    if execution_blocked or decision.decision == "needs_approval":
        reason = (
            "execution disabled"
            if not getattr(app_settings, "safety_execution_enabled", True)
            else "read-only mode"
            if getattr(app_settings, "safety_read_only", False)
            else decision.reason
        )
        command_class = "change" if execution_blocked else decision.command_class
        confirm_token = "" if execution_blocked else decision.confirm_token
        approval = crud.command_approval.create(
            db,
            user_id=current_user.id,
            connector_id=int(connector.id),
            event_id=None,
            command_text=text,
            command_class=command_class,
            reason=reason,
            confirm_token=confirm_token,
        )
        return TmuxSendResponse(
            status="needs_approval",
            reason=reason,
            target=str(config.get("target") or ""),
            approval_id=int(approval.id),
            confirm_token=approval.confirm_token or "",
        )

    instance = get_connector("tmux", config)
    timeout_seconds = max(
        1,
        int(getattr(app_settings, "safety_tmux_send_timeout_seconds", 8) or 8),
    )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                instance.send_message,
                {
                    "command": text,
                    "enter_count": int(payload.enter_count or 2),
                },
            ),
            timeout=timeout_seconds,
        )
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="tmux send timed out. Verify pane/session health and retry.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))

    resolved_target = ""
    if isinstance(result, dict):
        resolved_target = str(result.get("target") or "")
    if not resolved_target:
        resolved_target = str(config.get("target") or "")
    if not resolved_target and config.get("session"):
        resolved_target = f"{config.get('session')}:0.0"

    return TmuxSendResponse(
        status="sent",
        reason="sent",
        target=resolved_target,
        submit_mode=(
            str(result.get("submit_mode") or "") if isinstance(result, dict) else ""
        ),
    )


@router.get("/control/sessions", response_model=TmuxControlSessionsResponse)
async def list_control_sessions(
    socket_path: str = Query("", max_length=512),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = _control_session_records(
        db,
        current_user,
        socket_path=socket_path,
        include_stopped=False,
    )
    status_map = await _fetch_console_status_map(
        [
            str(record.get("web_url") or "")
            for record in records
            if bool(record.get("running"))
        ]
    )
    items = [
        TmuxControlSessionOut(
            session_name=str(record.get("session_name") or ""),
            windows=int(record.get("windows") or 0),
            attached=int(record.get("attached") or 0),
            target=str(record.get("target") or ""),
            pane_current_command=str(record.get("pane_current_command") or ""),
            pane_current_path=str(record.get("pane_current_path") or ""),
            managed=bool(record.get("managed")),
            connector_id=record.get("connector_id"),
            connector_name=str(record.get("connector_name") or ""),
            protected=bool(record.get("protected")),
            protected_reason=str(record.get("protected_reason") or ""),
            locked=bool(record.get("locked")),
            operator_mode=str(record.get("operator_mode") or "observe"),
            operator_note=str(record.get("operator_note") or ""),
            operator_updated_at=str(record.get("operator_updated_at") or ""),
            web_url=str(record.get("web_url") or ""),
            status_available=bool(
                status_map.get(str(record.get("web_url") or ""), {}).get("reachable")
            ),
            status_message=str(
                status_map.get(str(record.get("web_url") or ""), {}).get(
                    "status_message"
                )
                or ""
            ),
            auth_required=bool(
                status_map.get(str(record.get("web_url") or ""), {}).get(
                    "auth_required"
                )
            ),
            auth_mode=str(
                status_map.get(str(record.get("web_url") or ""), {}).get("auth_mode")
                or ""
            ),
            auth_summary=str(
                status_map.get(str(record.get("web_url") or ""), {}).get("auth_summary")
                or ""
            ),
            auth_verification_url=str(
                status_map.get(str(record.get("web_url") or ""), {}).get(
                    "auth_verification_url"
                )
                or ""
            ),
            auth_device_code=str(
                status_map.get(str(record.get("web_url") or ""), {}).get(
                    "auth_device_code"
                )
                or ""
            ),
        )
        for record in records
        if bool(record.get("running"))
    ]

    return TmuxControlSessionsResponse(items=items, count=len(items))


@router.get("/control/ops", response_model=TmuxControlOpsResponse)
async def list_control_ops(
    socket_path: str = Query("", max_length=512),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = _control_session_records(
        db,
        current_user,
        socket_path=socket_path,
        include_stopped=True,
    )
    status_map = await _fetch_console_status_map(
        [str(record.get("web_url") or "") for record in records]
    )
    items: list[TmuxControlOpsItemOut] = []

    for record in records:
        web_url = str(record.get("web_url") or "")
        status = status_map.get(web_url, _fetch_console_status(""))
        state, state_label, state_detail = _derive_ops_state(record, status)
        items.append(
            TmuxControlOpsItemOut(
                session_name=str(record.get("session_name") or ""),
                running=bool(record.get("running")),
                windows=int(record.get("windows") or 0),
                attached=int(record.get("attached") or 0),
                target=str(record.get("target") or ""),
                pane_current_command=str(record.get("pane_current_command") or ""),
                pane_current_path=str(record.get("pane_current_path") or ""),
                managed=bool(record.get("managed")),
                connector_id=record.get("connector_id"),
                connector_name=str(record.get("connector_name") or ""),
                protected=bool(record.get("protected")),
                protected_reason=str(record.get("protected_reason") or ""),
                locked=bool(record.get("locked")),
                operator_mode=str(record.get("operator_mode") or "observe"),
                operator_note=str(record.get("operator_note") or ""),
                operator_updated_at=str(record.get("operator_updated_at") or ""),
                web_url=web_url,
                status_available=bool(status.get("reachable")),
                pending=bool(status.get("pending")),
                has_response=bool(status.get("has_response")),
                needs_turn=(state == "needs_turn"),
                status_message=str(status.get("status_message") or ""),
                last_action=str(status.get("last_action") or ""),
                last_action_at=int(status.get("last_action_at") or 0),
                last_action_detail=str(status.get("last_action_detail") or ""),
                last_finished_at=int(status.get("last_finished_at") or 0),
                prompt_preview=str(status.get("prompt_preview") or ""),
                response_preview=str(status.get("response_preview") or ""),
                state=state,
                state_label=state_label,
                state_detail=state_detail,
                auth_required=bool(status.get("auth_required")),
                auth_mode=str(status.get("auth_mode") or ""),
                auth_summary=str(status.get("auth_summary") or ""),
                auth_verification_url=str(status.get("auth_verification_url") or ""),
                auth_device_code=str(status.get("auth_device_code") or ""),
            )
        )

    state_priority = {
        "needs_turn": 0,
        "working": 1,
        "manual": 2,
        "shared": 3,
        "locked": 4,
        "stopped": 5,
        "ready": 6,
        "live": 7,
    }
    items.sort(
        key=lambda item: (
            state_priority.get(item.state, 20),
            0 if item.managed else 1,
            item.connector_name.lower() or item.session_name.lower(),
        )
    )

    return TmuxControlOpsResponse(
        items=items,
        count=len(items),
        running=sum(1 for item in items if item.running),
        working=sum(1 for item in items if item.state == "working"),
        needs_turn=sum(1 for item in items if item.state == "needs_turn"),
        locked=sum(1 for item in items if item.state == "locked"),
        stopped=sum(1 for item in items if item.state == "stopped"),
    )


@router.post("/control/adopt", response_model=TmuxAdoptResponse)
async def adopt_control_session(
    payload: TmuxAdoptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = _normalize_session_name(payload.session)
    socket_path = str(payload.socket_path or "").strip()
    sessions = tmux_inspector.list_sessions(socket_path=socket_path)
    if session not in {str(item.get("session_name") or "") for item in sessions}:
        raise HTTPException(status_code=404, detail="tmux session not found")

    panes = tmux_inspector.list_panes(socket_path=socket_path)
    primary = _find_primary_session_pane(panes, session)
    target = str(primary.get("target") or f"{session}:0.0")
    working_dir = (
        str(payload.working_dir or "").strip()
        or str(primary.get("pane_current_path") or "").strip()
    )
    bootstrap = str(payload.bootstrap_command or "").strip()
    if not bootstrap and working_dir:
        bootstrap = _read_session_bootstrap_from_dir(working_dir)

    connector_name = str(payload.connector_name or "").strip() or f"tmux:{session}"
    connector = _upsert_connector_for_session(
        db=db,
        user=current_user,
        session=session,
        connector_name=connector_name,
        target=target,
        working_dir=working_dir,
        bootstrap_command=bootstrap,
        protected=bool(payload.protected),
    )

    channel: Optional[Channel] = None
    if payload.create_channel:
        channel = _ensure_channel_for_connector(
            db=db,
            connector=connector,
            requested_name=payload.channel_name,
            session=session,
        )
    bot: Optional[Bot] = None
    if payload.create_bot:
        bot = _ensure_bot_for_session(
            db=db,
            user=current_user,
            session=session,
            requested_name=payload.bot_name,
        )

    protected, _ = _is_protected_session(session, connector)
    return TmuxAdoptResponse(
        status="adopted",
        session=session,
        connector_id=int(connector.id),
        connector_name=str(connector.name or ""),
        channel_id=(int(channel.id) if channel else None),
        channel_name=(str(channel.name or "") if channel else ""),
        bot_id=(int(bot.id) if bot else None),
        bot_name=(str(bot.name or "") if bot else ""),
        protected=protected,
        target=target,
    )


@router.post("/control/adopt_all", response_model=TmuxAdoptAllResponse)
async def adopt_all_control_sessions(
    payload: TmuxAdoptAllRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    socket_path = str(payload.socket_path or "").strip()
    sessions = tmux_inspector.list_sessions(socket_path=socket_path)
    panes = tmux_inspector.list_panes(socket_path=socket_path)
    results: list[TmuxAdoptResponse] = []
    skipped = 0

    for item in sessions:
        session_name = _normalize_session_name(str(item.get("session_name") or ""))
        protected, _ = _is_protected_session(session_name)
        if protected and not payload.include_protected:
            skipped += 1
            continue
        primary = _find_primary_session_pane(panes, session_name)
        target = str(primary.get("target") or f"{session_name}:0.0")
        working_dir = str(primary.get("pane_current_path") or "").strip()
        bootstrap = _read_session_bootstrap_from_dir(working_dir) if working_dir else ""
        connector = _upsert_connector_for_session(
            db=db,
            user=current_user,
            session=session_name,
            connector_name=f"tmux:{session_name}",
            target=target,
            working_dir=working_dir,
            bootstrap_command=bootstrap,
            protected=protected,
        )
        channel: Optional[Channel] = None
        if payload.create_channels:
            channel = _ensure_channel_for_connector(
                db=db,
                connector=connector,
                requested_name=f"Console - {session_name}",
                session=session_name,
            )
        bot: Optional[Bot] = None
        if payload.create_bots:
            bot = _ensure_bot_for_session(
                db=db,
                user=current_user,
                session=session_name,
                requested_name=f"Agent - {session_name}",
            )

        results.append(
            TmuxAdoptResponse(
                status="adopted",
                session=session_name,
                connector_id=int(connector.id),
                connector_name=str(connector.name or ""),
                channel_id=(int(channel.id) if channel else None),
                channel_name=(str(channel.name or "") if channel else ""),
                bot_id=(int(bot.id) if bot else None),
                bot_name=(str(bot.name or "") if bot else ""),
                protected=protected,
                target=target,
            )
        )

    return TmuxAdoptAllResponse(
        status="ok",
        adopted=len(results),
        skipped=skipped,
        items=results,
    )


@router.post("/control/start", response_model=TmuxSessionActionResponse)
async def start_control_session(
    payload: TmuxSessionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    socket_path = str(payload.socket_path or "").strip()
    cfg = dict(connector.config or {}) if connector else {}
    tmux_hold_reason = tmux_commands_block_reason(get_settings())
    if tmux_hold_reason:
        raise HTTPException(status_code=423, detail=tmux_hold_reason)
    locked = _is_locked_session(connector)
    if locked:
        raise HTTPException(
            status_code=423,
            detail="Session is locked by failsafe policy; unlock before starting.",
        )
    target = str(payload.target or "").strip() or str(
        cfg.get("target") or f"{session}:0.0"
    )
    working_dir = str(payload.working_dir or "").strip() or str(
        cfg.get("working_dir") or ""
    )
    bootstrap = str(payload.bootstrap_command or "").strip() or str(
        cfg.get("session_bootstrap") or ""
    )
    if not bootstrap and working_dir:
        bootstrap = _read_session_bootstrap_from_dir(working_dir)

    try:
        started_session, launched_command, resolved_target = (
            _ensure_tmux_session_running(
                session=session,
                target=target,
                working_dir=working_dir,
                bootstrap_command=bootstrap,
                socket_path=socket_path,
                force_restart=bool(payload.force_restart),
            )
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))

    if connector:
        next_cfg = dict(cfg)
        next_cfg["session"] = session
        next_cfg["target"] = resolved_target
        if working_dir:
            next_cfg["working_dir"] = working_dir
        if bootstrap:
            next_cfg["session_bootstrap"] = bootstrap
        if next_cfg != cfg:
            connector.config = next_cfg
            db.add(connector)
            db.commit()
            db.refresh(connector)

    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        target=resolved_target,
        detail="started",
        started_session=started_session,
        launched_command=launched_command,
        locked=locked,
        web_url=_web_url(connector),
    )


@router.post("/control/stop", response_model=TmuxSessionActionResponse)
async def stop_control_session(
    payload: TmuxSessionStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    protected, _ = _is_protected_session(session, connector)
    locked = _is_locked_session(connector)
    if protected and not payload.force:
        raise HTTPException(
            status_code=403,
            detail="Session is protected; pass force=true to stop it.",
        )

    socket_path = str(payload.socket_path or "").strip()
    if not _tmux_has_session(session, socket_path=socket_path):
        return TmuxSessionActionResponse(
            status="not_found",
            session=session,
            detail="Session not running",
            protected=protected,
            locked=locked,
            web_url=_web_url(connector),
        )

    try:
        _run_tmux("kill-session", "-t", session, socket_path=socket_path, check=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=503, detail=_normalize_tmux_runtime_error(exc))

    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail="stopped",
        stopped_session=True,
        protected=protected,
        locked=locked,
        web_url=_web_url(connector),
    )


@router.post("/control/restart", response_model=TmuxSessionActionResponse)
async def restart_control_session(
    payload: TmuxSessionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    tmux_hold_reason = tmux_commands_block_reason(get_settings())
    if tmux_hold_reason:
        raise HTTPException(status_code=423, detail=tmux_hold_reason)
    if _is_locked_session(connector):
        raise HTTPException(
            status_code=423,
            detail="Session is locked by failsafe policy; unlock before restarting.",
        )
    protected, _ = _is_protected_session(session, connector)
    if protected:
        raise HTTPException(status_code=403, detail="Session is protected")

    socket_path = str(payload.socket_path or "").strip()
    if _tmux_has_session(session, socket_path=socket_path):
        _run_tmux("kill-session", "-t", session, socket_path=socket_path, check=True)

    # Reuse start path with force restart.
    start_payload = TmuxSessionStartRequest(
        session=session,
        connector_id=(int(connector.id) if connector else None),
        socket_path=socket_path,
        target=payload.target,
        working_dir=payload.working_dir,
        bootstrap_command=payload.bootstrap_command,
        force_restart=True,
    )
    return await start_control_session(
        payload=start_payload,
        db=db,
        current_user=current_user,
    )


@router.post("/control/lock", response_model=TmuxSessionActionResponse)
async def lock_control_session(
    payload: TmuxSessionLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    if connector is None:
        raise HTTPException(
            status_code=404,
            detail="Managed tmux connector not found for this session.",
        )

    protected, _ = _is_protected_session(session, connector)
    locked = bool(payload.locked)
    cfg = dict(connector.config or {})
    cfg["locked"] = locked
    connector.config = cfg
    db.add(connector)
    db.commit()
    db.refresh(connector)

    stopped = False
    socket_path = str(payload.socket_path or "").strip()
    if (
        locked
        and payload.stop_session
        and _tmux_has_session(session, socket_path=socket_path)
    ):
        if protected and not payload.force:
            raise HTTPException(
                status_code=403,
                detail="Session is protected; pass force=true to stop it while locking.",
            )
        try:
            _run_tmux(
                "kill-session",
                "-t",
                session,
                socket_path=socket_path,
                check=True,
            )
            stopped = True
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503, detail=_normalize_tmux_runtime_error(exc)
            )
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=503, detail=_normalize_tmux_runtime_error(exc)
            )

    detail = "locked" if locked else "unlocked"
    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail=detail,
        stopped_session=stopped,
        protected=protected,
        locked=locked,
        operator_mode=_operator_mode(connector),
        operator_note=_operator_note(connector),
        operator_updated_at=_operator_updated_at(connector),
        web_url=_web_url(connector),
    )


@router.post("/control/operator", response_model=TmuxSessionActionResponse)
async def set_control_operator_mode(
    payload: TmuxSessionOperatorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    if not connector:
        raise HTTPException(
            status_code=404,
            detail="Managed tmux connector not found for this session.",
        )

    mode = _normalize_operator_mode(payload.mode)
    note = str(payload.note or "").strip()
    cfg = dict(connector.config or {})
    cfg["operator_mode"] = mode
    cfg["operator_note"] = note
    cfg["operator_updated_at"] = datetime.now(timezone.utc).isoformat()
    connector.config = cfg
    db.add(connector)
    db.commit()
    db.refresh(connector)

    detail = (
        "operator takeover active"
        if mode == "take"
        else "operator shared mode active"
        if mode == "co_pilot"
        else "operator takeover released"
    )
    protected, _ = _is_protected_session(session, connector)
    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail=detail,
        protected=protected,
        locked=_is_locked_session(connector),
        operator_mode=_operator_mode(connector),
        operator_note=_operator_note(connector),
        operator_updated_at=_operator_updated_at(connector),
        web_url=_web_url(connector),
    )


@router.post("/control/web-url", response_model=TmuxSessionActionResponse)
async def set_control_web_url(
    payload: TmuxSessionWebUrlRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    if not connector:
        raise HTTPException(
            status_code=404,
            detail="Managed tmux connector not found for this session.",
        )

    web_url = _normalize_web_url(payload.web_url)
    cfg = dict(connector.config or {})
    if web_url:
        cfg["web_url"] = web_url
    else:
        cfg.pop("web_url", None)
    connector.config = cfg
    db.add(connector)
    db.commit()
    db.refresh(connector)

    protected, _ = _is_protected_session(session, connector)
    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail="web link saved" if web_url else "web link cleared",
        protected=protected,
        locked=_is_locked_session(connector),
        operator_mode=_operator_mode(connector),
        operator_note=_operator_note(connector),
        operator_updated_at=_operator_updated_at(connector),
        web_url=_web_url(connector),
    )


@router.post("/control/auth-device", response_model=TmuxSessionActionResponse)
async def start_control_auth_device(
    payload: TmuxSessionAuthRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    if not connector:
        raise HTTPException(
            status_code=404,
            detail="Managed tmux connector not found for this session.",
        )

    web_url = _web_url(connector)
    remote = _post_console_action(web_url, "/api/auth/device")
    snapshot = (
        remote.get("snapshot") if isinstance(remote.get("snapshot"), dict) else {}
    )
    auth = _console_auth_state(snapshot)
    protected, _ = _is_protected_session(session, connector)

    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail=str(
            remote.get("detail") or auth.get("auth_summary") or "Auth step started."
        ),
        protected=protected,
        locked=_is_locked_session(connector),
        operator_mode=_operator_mode(connector),
        operator_note=_operator_note(connector),
        operator_updated_at=_operator_updated_at(connector),
        web_url=web_url,
        auth_required=bool(auth.get("auth_required")),
        auth_mode=str(auth.get("auth_mode") or ""),
        auth_summary=str(auth.get("auth_summary") or ""),
        auth_verification_url=str(auth.get("auth_verification_url") or ""),
        auth_device_code=str(auth.get("auth_device_code") or ""),
    )


@router.post("/control/auth-browser", response_model=TmuxSessionActionResponse)
async def start_control_auth_browser(
    payload: TmuxSessionAuthRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session, connector = _resolve_control_session(
        db=db,
        user=current_user,
        session=payload.session,
        connector_id=payload.connector_id,
    )
    if not connector:
        raise HTTPException(
            status_code=404,
            detail="Managed tmux connector not found for this session.",
        )

    web_url = _web_url(connector)
    remote = _post_console_action(web_url, "/api/auth/browser")
    snapshot = (
        remote.get("snapshot") if isinstance(remote.get("snapshot"), dict) else {}
    )
    auth = _console_auth_state(snapshot)
    protected, _ = _is_protected_session(session, connector)

    return TmuxSessionActionResponse(
        status="ok",
        session=session,
        detail=str(
            remote.get("detail") or auth.get("auth_summary") or "Auth step started."
        ),
        protected=protected,
        locked=_is_locked_session(connector),
        operator_mode=_operator_mode(connector),
        operator_note=_operator_note(connector),
        operator_updated_at=_operator_updated_at(connector),
        web_url=web_url,
        auth_required=bool(auth.get("auth_required")),
        auth_mode=str(auth.get("auth_mode") or ""),
        auth_summary=str(auth.get("auth_summary") or ""),
        auth_verification_url=str(auth.get("auth_verification_url") or ""),
        auth_device_code=str(auth.get("auth_device_code") or ""),
    )


@router.post("/control/lock-all", response_model=TmuxLockAllResponse)
async def lock_all_control_sessions(
    payload: TmuxLockAllRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connectors = (
        db.query(Connector)
        .filter(
            Connector.user_id == current_user.id, Connector.connector_type == "tmux"
        )
        .order_by(Connector.id.asc())
        .all()
    )
    locked = bool(payload.locked)
    socket_path = str(payload.socket_path or "").strip()
    updated = 0
    stopped = 0
    skipped_protected = 0

    for connector in connectors:
        session = _connector_session_name(connector)
        if not session:
            continue
        protected, _ = _is_protected_session(session, connector)
        if protected and not payload.include_protected:
            skipped_protected += 1
            continue

        cfg = dict(connector.config or {})
        if bool(cfg.get("locked")) != locked:
            cfg["locked"] = locked
            if locked:
                cfg["locked_reason"] = "bulk-lock"
            connector.config = cfg
            db.add(connector)
            updated += 1

        if (
            locked
            and payload.stop_sessions
            and _tmux_has_session(session, socket_path=socket_path)
        ):
            if protected and not payload.force:
                skipped_protected += 1
                continue
            _run_tmux(
                "kill-session", "-t", session, socket_path=socket_path, check=False
            )
            stopped += 1

    if updated:
        db.commit()
    else:
        db.rollback()

    return TmuxLockAllResponse(
        status="ok",
        locked=locked,
        updated=updated,
        stopped_sessions=stopped,
        skipped_protected=skipped_protected,
    )


@router.get("/control/profiles", response_model=TmuxProfileListResponse)
async def list_tmux_profiles(current_user: User = Depends(get_current_user)):
    profile_dir = _profile_dir_for_user(current_user)
    items: list[TmuxProfileSummary] = []
    for path in sorted(profile_dir.glob("*.json"), reverse=True):
        try:
            updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        items.append(
            TmuxProfileSummary(
                name=path.stem,
                updated_at=updated.isoformat(),
            )
        )
    return TmuxProfileListResponse(items=items, count=len(items))


@router.post("/control/profiles/save", response_model=TmuxProfileActionResponse)
async def save_tmux_profile(
    payload: TmuxProfileSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile_path = _profile_path(current_user, payload.name)
    snapshot = _session_profile_payload(
        db,
        current_user,
        running_only=bool(payload.running_only),
        include_protected=bool(payload.include_protected),
        socket_path=str(payload.socket_path or "").strip(),
    )
    profile_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    return TmuxProfileActionResponse(
        status="saved",
        name=payload.name,
        sessions=len(snapshot.get("items") or []),
        applied=len(snapshot.get("items") or []),
    )


@router.post("/control/profiles/load", response_model=TmuxProfileActionResponse)
async def load_tmux_profile(
    payload: TmuxProfileLoadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile_path = _profile_path(current_user, payload.name)
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid profile file")

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Invalid profile payload")

    applied = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        session = _normalize_session_name(str(item.get("session") or ""))
        connector = _upsert_connector_for_session(
            db=db,
            user=current_user,
            session=session,
            connector_name=str(item.get("connector_name") or f"tmux:{session}"),
            target=str(item.get("target") or f"{session}:0.0"),
            working_dir=str(item.get("working_dir") or ""),
            bootstrap_command=str(item.get("session_bootstrap") or ""),
            protected=bool(item.get("protected")),
        )
        if "web_url" in item:
            item_web_url = _normalize_web_url(str(item.get("web_url") or ""))
            cfg = dict(connector.config or {})
            current_web_url = str(cfg.get("web_url") or "").strip()
            if item_web_url:
                if current_web_url != item_web_url:
                    cfg["web_url"] = item_web_url
                    connector.config = cfg
                    db.add(connector)
                    db.commit()
                    db.refresh(connector)
            elif current_web_url:
                cfg.pop("web_url", None)
                connector.config = cfg
                db.add(connector)
                db.commit()
                db.refresh(connector)
        protected, _ = _is_protected_session(session, connector)
        if protected and not payload.include_protected:
            continue
        if payload.start_sessions:
            _ensure_tmux_session_running(
                session=session,
                target=str(item.get("target") or f"{session}:0.0"),
                working_dir=str(item.get("working_dir") or ""),
                bootstrap_command=str(item.get("session_bootstrap") or ""),
                force_restart=bool(payload.force_restart),
            )
        applied += 1

    return TmuxProfileActionResponse(
        status="loaded",
        name=payload.name,
        sessions=len(items),
        applied=applied,
    )


@router.post("/control/profiles/rename", response_model=TmuxProfileActionResponse)
async def rename_tmux_profile(
    payload: TmuxProfileRenameRequest,
    current_user: User = Depends(get_current_user),
):
    from_name = _normalize_profile_name(payload.from_name)
    to_name = _normalize_profile_name(payload.to_name)
    source_path = _profile_path(current_user, from_name)
    target_path = _profile_path(current_user, to_name)

    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")

    if (
        source_path != target_path
        and target_path.exists()
        and not bool(payload.overwrite)
    ):
        raise HTTPException(
            status_code=409,
            detail="Target profile already exists; pass overwrite=true to replace it.",
        )

    sessions = _profile_session_count(source_path)
    try:
        if source_path != target_path:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(target_path)
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to rename profile")

    return TmuxProfileActionResponse(
        status="renamed",
        name=to_name,
        sessions=sessions,
        applied=sessions,
    )


@router.delete("/control/profiles/{name}", response_model=TmuxProfileActionResponse)
async def delete_tmux_profile(
    name: str,
    current_user: User = Depends(get_current_user),
):
    profile_name = _normalize_profile_name(name)
    profile_path = _profile_path(current_user, profile_name)
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")

    sessions = _profile_session_count(profile_path)
    try:
        profile_path.unlink()
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to delete profile")

    return TmuxProfileActionResponse(
        status="deleted",
        name=profile_name,
        sessions=sessions,
        applied=sessions,
    )
