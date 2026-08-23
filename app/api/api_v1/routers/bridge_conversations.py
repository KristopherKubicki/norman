import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from app.api.deps import get_console_runtime_user, get_db
from app.models import (
    BridgeConversationRecord,
    Connector,
    EstateBot,
    EstateService,
    User,
)
from app.services.console_status import fetch_console_history

router = APIRouter(prefix="/bridge/conversations", tags=["bridge_conversations"])


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _is_legacy_bridge_diagnostic(item: dict[str, Any]) -> bool:
    text = "\n".join(
        str(item.get(field) or "").strip()
        for field in ("prompt", "response", "result", "error")
    )
    return bool(
        re.search(
            r"prior bridge status|characters omitted from live transport|"
            r"bridge opening the estate|this diagnostic reply has been superseded|"
            r"this status used deterministic tui state|"
            r"selected route:\s*codex/gpt-5\.4|"
            r"\[auto-continuation:",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    )


def _bridge_history_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if _is_legacy_bridge_diagnostic(item):
            continue
        normalized.append(dict(item))
    return normalized


def _connector_agent_slugs(connector: Connector) -> set[str]:
    config = dict(connector.config or {})
    values = [
        config.get("agent_slug"),
        config.get("agent_name"),
        config.get("slug"),
        config.get("session"),
        connector.name,
    ]
    slugs: set[str] = set()
    for value in values:
        normalized = _slug(value)
        if not normalized:
            continue
        slugs.add(normalized)
        if normalized.startswith("tmux-"):
            slugs.add(normalized[5:])
        if normalized.endswith("-bot"):
            slugs.add(normalized[:-4])
    return slugs


def _history_connector(
    db: Session, current_user: User, agent_slug: str
) -> Optional[Connector]:
    target = _slug(agent_slug)
    rows = (
        db.query(Connector)
        .filter(
            Connector.user_id == current_user.id,
            Connector.connector_type == "tmux",
        )
        .order_by(Connector.id.asc())
        .all()
    )
    exact = [row for row in rows if target in _connector_agent_slugs(row)]
    if exact:
        return exact[0]
    target_base = target[:-4] if target.endswith("-bot") else target
    for row in rows:
        if target_base in _connector_agent_slugs(row):
            return row
    return None


def _estate_history_url(db: Session, agent_slug: str) -> str:
    target = _slug(agent_slug)
    services = (
        db.query(EstateService)
        .filter(EstateService.is_active.is_(True))
        .order_by(EstateService.id.asc())
        .all()
    )
    service = next(
        (
            item
            for item in services
            if target in {_slug(item.slug), _slug(item.display_name)}
        ),
        None,
    )
    if service is not None:
        return str(
            service.console_url_tailnet
            or service.console_url
            or service.web_url_tailnet
            or service.web_url
            or ""
        ).strip()
    bots = db.query(EstateBot).filter(EstateBot.is_active.is_(True)).all()
    bot = next((item for item in bots if _slug(item.slug) == target), None)
    if bot is None and target.endswith("-bot"):
        bot = next(
            (item for item in bots if _slug(item.slug) == target[:-4]),
            None,
        )
    if bot is None:
        return ""
    service = next((item for item in services if item.bot_id == bot.id), None)
    if service is None:
        return ""
    return str(
        service.console_url_tailnet
        or service.console_url
        or service.web_url_tailnet
        or service.web_url
        or ""
    ).strip()


def _station_target(
    db: Session, current_user: User, agent_slug: str
) -> tuple[str, str]:
    connector = _history_connector(db, current_user, agent_slug)
    config = dict(connector.config or {}) if connector else {}
    return (
        str(config.get("collector_url") or config.get("web_url") or "").strip()
        or _estate_history_url(db, agent_slug),
        str(config.get("web_token") or "").strip(),
    )


def _station_api_url(web_url: str, path: str) -> tuple[str, str]:
    parts = urlsplit(str(web_url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return "", ""
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    base_path = parts.path.rstrip("/")
    return (
        urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                f"{base_path}{path}",
                "",
                "",
            )
        ),
        str(query.get("token") or "").strip(),
    )


def _submit_station_prompt(
    web_url: str,
    *,
    access_token: str,
    message: str,
    submission_id: str,
) -> Dict[str, Any]:
    ask_url, query_token = _station_api_url(web_url, "/api/ask")
    if not ask_url:
        raise RuntimeError("Station endpoint is unavailable")
    form = {
        "message": message,
        "submission_id": submission_id,
        "speed": "careful",
        "detail": "3",
        "bridge_direct": "1",
    }
    token = str(access_token or query_token).strip()
    if token:
        form["token"] = token
    request = UrlRequest(
        ask_url,
        data=urlencode(form).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "NormanBridge/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        raise RuntimeError(
            str(payload.get("error") or f"Station rejected the prompt ({exc.code})")
        ) from exc
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Station prompt failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Station returned an invalid prompt receipt")
    return payload


def _fetch_station_file(
    web_url: str,
    *,
    access_token: str,
    path: str,
    max_bytes: int = 32 * 1024 * 1024,
) -> tuple[bytes, str]:
    file_url, query_token = _station_api_url(web_url, "/api/file")
    if not file_url:
        raise RuntimeError("Station file endpoint is unavailable")
    query = {"path": path, "raw": "1"}
    token = str(access_token or query_token).strip()
    if token:
        query["token"] = token
    request = UrlRequest(
        f"{file_url}?{urlencode(query, quote_via=quote)}",
        headers={
            "Accept": "*/*",
            "User-Agent": "NormanBridge/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > max_bytes:
                raise RuntimeError("Station attachment is too large")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError("Station attachment is too large")
            return (
                body,
                str(response.headers.get_content_type() or "application/octet-stream"),
            )
    except HTTPError as exc:
        raise RuntimeError(f"Station attachment is unavailable ({exc.code})") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Station attachment failed: {exc}") from exc


def _members(values: List[str]) -> List[str]:
    return list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


class BridgeConversationCreate(BaseModel):
    kind: Literal["room", "direct"]
    title: str = Field(default="", max_length=120)
    principal_slug: str = Field(default="", max_length=120)
    domain_slug: str = Field(default="", max_length=120)
    direct_agent_slug: Optional[str] = Field(default=None, max_length=120)
    member_slugs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator("title", "principal_slug", "domain_slug", "direct_agent_slug", pre=True)
    def strip_strings(cls, value):
        return str(value or "").strip()

    @validator("member_slugs", pre=True)
    def normalize_members(cls, value):
        return _members(value or [])


class BridgeConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    domain_slug: Optional[str] = Field(default=None, max_length=120)
    member_slugs: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    @validator("title", "domain_slug", pre=True)
    def strip_strings(cls, value):
        return None if value is None else str(value).strip()

    @validator("member_slugs", pre=True)
    def normalize_members(cls, value):
        return None if value is None else _members(value)


class BridgeAgentMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=100000)
    conversation_id: str = Field(default="", max_length=120)
    submission_id: str = Field(default="", max_length=160)

    @validator("message", "conversation_id", "submission_id", pre=True)
    def strip_message_fields(cls, value):
        return str(value or "").strip()


def _payload(record: BridgeConversationRecord) -> Dict[str, Any]:
    return {
        "conversation_id": record.conversation_id,
        "kind": record.kind,
        "title": record.title,
        "principal_slug": record.principal_slug,
        "domain_slug": record.domain_slug,
        "direct_agent_slug": record.direct_agent_slug or "",
        "member_slugs": list(record.member_slugs_json or []),
        "metadata": dict(record.metadata_json or {}),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _owned(
    db: Session, current_user: User, conversation_id: str
) -> BridgeConversationRecord:
    record = (
        db.query(BridgeConversationRecord)
        .filter(
            BridgeConversationRecord.user_id == current_user.id,
            BridgeConversationRecord.conversation_id == conversation_id,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return record


@router.get("")
async def list_bridge_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    records = (
        db.query(BridgeConversationRecord)
        .filter(BridgeConversationRecord.user_id == current_user.id)
        .order_by(
            BridgeConversationRecord.updated_at.desc(),
            BridgeConversationRecord.created_at.desc(),
        )
        .all()
    )
    return {"items": [_payload(record) for record in records]}


@router.get("/agents/{agent_slug}/history")
async def get_bridge_agent_history(
    agent_slug: str,
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    connector = _history_connector(db, current_user, agent_slug)
    config = dict(connector.config or {}) if connector else {}
    web_url = (
        str(config.get("collector_url") or config.get("web_url") or "").strip()
        or _estate_history_url(db, agent_slug)
        or f"{str(request.base_url).rstrip('/')}/bot/{_slug(agent_slug)}/"
    )
    snapshot = await asyncio.to_thread(
        fetch_console_history,
        web_url,
        access_token=str(config.get("web_token") or "").strip(),
        limit=max(1, min(int(limit or 100), 250)),
    )
    if not snapshot.get("reachable"):
        raise HTTPException(status_code=503, detail="Station history is unavailable")
    return {
        "agent_slug": _slug(agent_slug),
        "agent_name": snapshot.get("agent_name")
        or (connector.name if connector else "")
        or agent_slug,
        "thread_id": snapshot.get("thread_id") or "",
        "items": _bridge_history_items(snapshot.get("items")),
    }


@router.get("/agents/{agent_slug}/media/{attachment_token}")
async def get_bridge_agent_media(
    agent_slug: str,
    attachment_token: str,
    request: Request,
    download: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    slug = _slug(agent_slug)
    web_url, access_token = _station_target(db, current_user, slug)
    web_url = web_url or f"{str(request.base_url).rstrip('/')}/bot/{slug}/"
    snapshot = await asyncio.to_thread(
        fetch_console_history,
        web_url,
        access_token=access_token,
        limit=250,
        timeout=8.0,
    )
    if not snapshot.get("reachable"):
        raise HTTPException(status_code=503, detail="Station media is unavailable")
    attachment = next(
        (
            item
            for turn in snapshot.get("items") or []
            for item in turn.get("attachments") or []
            if str(item.get("token") or "") == attachment_token
        ),
        None,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        body, content_type = await asyncio.to_thread(
            _fetch_station_file,
            web_url,
            access_token=access_token,
            path=str(attachment.get("path") or ""),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    filename = str(attachment.get("name") or attachment_token).replace('"', "")
    disposition = "attachment" if download else "inline"
    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/agents/{agent_slug}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_bridge_agent_message(
    agent_slug: str,
    payload: BridgeAgentMessageCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    slug = _slug(agent_slug)
    if payload.conversation_id:
        conversation = _owned(db, current_user, payload.conversation_id)
        if (
            conversation.kind != "direct"
            or _slug(conversation.direct_agent_slug) != slug
        ):
            raise HTTPException(
                status_code=409,
                detail="Conversation does not target this station",
            )
    web_url, access_token = _station_target(db, current_user, slug)
    web_url = web_url or f"{str(request.base_url).rstrip('/')}/bot/{slug}/"
    if not web_url:
        raise HTTPException(status_code=503, detail="Station endpoint is unavailable")
    submission_id = payload.submission_id or f"bridge-{uuid4().hex}"
    try:
        receipt = await asyncio.to_thread(
            _submit_station_prompt,
            web_url,
            access_token=access_token,
            message=payload.message,
            submission_id=submission_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "agent_slug": slug,
        "submission_id": submission_id,
        "accepted": bool(receipt.get("accepted")),
        "queued": bool(receipt.get("queued")),
        "running": bool(receipt.get("running")),
        "submission_state": str(receipt.get("submission_state") or ""),
        "queue_position": int(receipt.get("queue_position") or 0),
        "error": str(receipt.get("error") or ""),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bridge_conversation(
    request: BridgeConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    members = _members(request.member_slugs)
    direct_agent = str(request.direct_agent_slug or "").strip()
    if request.kind == "direct":
        direct_agent = direct_agent or (members[0] if len(members) == 1 else "")
        if not direct_agent:
            raise HTTPException(
                status_code=422, detail="Direct messages require one agent"
            )
        members = [direct_agent]
        existing = (
            db.query(BridgeConversationRecord)
            .filter(
                BridgeConversationRecord.user_id == current_user.id,
                BridgeConversationRecord.kind == "direct",
                BridgeConversationRecord.principal_slug == request.principal_slug,
                BridgeConversationRecord.direct_agent_slug == direct_agent,
            )
            .first()
        )
        if existing:
            return _payload(existing)
    elif not request.title:
        raise HTTPException(status_code=422, detail="Rooms require a name")
    elif not members:
        raise HTTPException(status_code=422, detail="Rooms require at least one agent")

    title = request.title or direct_agent
    record = BridgeConversationRecord(
        user_id=current_user.id,
        conversation_id=f"conversation_{uuid4().hex}",
        kind=request.kind,
        title=title,
        principal_slug=request.principal_slug,
        domain_slug=request.domain_slug,
        direct_agent_slug=direct_agent or None,
        member_slugs_json=members,
        metadata_json=request.metadata,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _payload(record)


@router.patch("/{conversation_id}")
async def update_bridge_conversation(
    conversation_id: str,
    request: BridgeConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    record = _owned(db, current_user, conversation_id)
    changes = request.dict(exclude_unset=True)
    if "title" in changes:
        if record.kind == "room" and not changes["title"]:
            raise HTTPException(status_code=422, detail="Rooms require a name")
        record.title = changes["title"] or record.title
    if "domain_slug" in changes:
        record.domain_slug = changes["domain_slug"] or ""
    if "member_slugs" in changes:
        members = _members(changes["member_slugs"] or [])
        if not members:
            raise HTTPException(
                status_code=422, detail="Conversations require an agent"
            )
        if record.kind == "direct" and members != [record.direct_agent_slug]:
            raise HTTPException(
                status_code=422, detail="Direct message membership is fixed"
            )
        record.member_slugs_json = members
    if "metadata" in changes:
        record.metadata_json = changes["metadata"] or {}
    record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return _payload(record)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bridge_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_console_runtime_user),
):
    record = _owned(db, current_user, conversation_id)
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
