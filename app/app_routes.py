from typing import Any, List, Optional, Dict
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from fastapi import status
from fastapi.security import OAuth2PasswordRequestForm

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse, Response, JSONResponse
from starlette.responses import RedirectResponse

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.schemas import Token
from app.schemas.user import UserAuthenticate, UserCreate
from app.schemas.bot import Bot, BotCreate, BotOut, BotUpdate
from app.schemas.message import Message, MessageUpdate
from app.schemas.interaction import InteractionCreate
from app.core.config import active_config_file_path, settings
from app.core.safety_controls import (
    clamp_kill_switch_level,
    current_kill_switch_level,
    effective_read_only,
    execution_blocked_reason,
    kill_switch_label,
    routing_actions_block_reason,
    tmux_commands_block_reason,
)
from app.core.security import create_access_token
from app.crud.user import authenticate_user
from app.crud.user import (
    get_user_by_email,
    create_user,
    create_admin_user,
    is_admin_user_exists,
)
from app.crud.bot import (
    create_bot,
    delete_bot,
    get_bot_by_id,
    get_bots_by_user_id,
    update_bot,
)
from app.crud import connector as connector_crud
from app.crud.message import (
    create_message,
    get_messages_by_bot_id,
    get_message_by_id,
    delete_message,
    get_last_messages_by_bot_id,
    delete_messages_by_bot_id,
    update_message,
)
from app.crud.interaction import create_interaction
from app.crud import routing as routing_crud
from app.schemas.routing import RoutingRuleCreate
from app.handlers.openai_handler import create_chat_interaction
from app.core.exceptions import APIError
from app.core.logging import setup_logger
from app.api.deps import get_async_db, get_current_user
from app.models import User

try:
    from app.services.llm_runtime import get_llm_runtime_status
except ImportError:  # pragma: no cover - older live hosts may not have this module yet
    get_llm_runtime_status = None

try:
    from app.services.model_ping import list_model_ping_targets, ping_model_targets
except ImportError:  # pragma: no cover - older live hosts may not have this module yet
    list_model_ping_targets = None
    ping_model_targets = None

try:
    from app.services.norllama.mesh_cache import get_mesh_overview
    from app.services.norllama.warm_policy import apply_warm_policy, build_warm_policy
except ImportError:  # pragma: no cover - older live hosts may not have this module yet
    get_mesh_overview = None
    build_warm_policy = None
    apply_warm_policy = None

try:
    from app.services.norllama.gateway import fetch_tool_activity
except ImportError:  # pragma: no cover - older live hosts may not have this module yet
    fetch_tool_activity = None

from datetime import timedelta
from datetime import datetime, timezone
import inspect
import os
import uuid
import requests
import jwt
import json
import yaml
from urllib.parse import urlencode
import traceback
from threading import Lock

from .views import (
    home,
    connectors,
    filters,
    channels,
    process_message,
    bots,
    systems,
    messages,
    consoles,
    captions,
    login,
    logout,
    quickstart,
    setup,
    settings_page,
)
from app.connectors.connector_utils import get_connector, connector_classes
from app.services.connector_oauth import oauth_capability
from app.schemas.connector import ConnectorCreate, ConnectorUpdate, Connector
from app import models
from app.db import session as db_session

current_dir = os.path.dirname(os.path.realpath(__file__))
app_routes = APIRouter()
logger = setup_logger(__name__)
_console_heartbeats_lock = Lock()
_console_heartbeats: dict[str, dict[str, Any]] = {}
_CONSOLE_HEARTBEAT_MAX_ITEMS = 512
_CONSOLE_HEARTBEAT_MAX_AGE_SECONDS = 60 * 60 * 24


def _norman_chat_redirect_url(request: Request) -> str:
    request_host = (request.headers.get("host") or "").split(":", 1)[0].strip().lower()
    if request_host in {"switchboard.home.arpa", "switchboard.norman.home.arpa"}:
        return "/dashboard.html?view=switchboard"
    params: dict[str, str] = {}
    profile = str(request.query_params.get("profile") or "").strip()
    if profile:
        params["profile"] = profile
    route = str(request.query_params.get("route") or "").strip()
    if route:
        params["route"] = route
    return f"/bot/norman/?{urlencode(params)}" if params else "/bot/norman/"


def _console_heartbeat_now() -> tuple[float, str]:
    now = datetime.now(timezone.utc)
    return now.timestamp(), now.isoformat(timespec="seconds").replace("+00:00", "Z")


def _prune_console_heartbeats(now_ts: float) -> None:
    stale_before = now_ts - _CONSOLE_HEARTBEAT_MAX_AGE_SECONDS
    stale_keys = [
        key
        for key, item in _console_heartbeats.items()
        if float(item.get("seen_ts") or 0) < stale_before
    ]
    for key in stale_keys:
        _console_heartbeats.pop(key, None)
    if len(_console_heartbeats) <= _CONSOLE_HEARTBEAT_MAX_ITEMS:
        return
    ordered = sorted(
        _console_heartbeats.items(),
        key=lambda item: float(item[1].get("seen_ts") or 0),
        reverse=True,
    )
    for key, _ in ordered[_CONSOLE_HEARTBEAT_MAX_ITEMS:]:
        _console_heartbeats.pop(key, None)


@app_routes.get("/health")
async def health() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


@app_routes.get("/api/console-ui/ping", status_code=204)
async def console_ui_ping(
    request: Request,
    agent: str = "",
    ui_version: str = "",
    profile: str = "",
    route: str = "",
    href: str = "",
    host: str = "",
):
    now_ts, now_iso = _console_heartbeat_now()
    clean_agent = str(agent or "").strip() or "unknown"
    clean_profile = str(profile or "").strip() or "default"
    clean_host = str(host or "").strip() or request.headers.get("host", "") or "unknown"
    key = f"{clean_agent}|{clean_host}|{clean_profile}"
    payload = {
        "agent": clean_agent,
        "ui_version": str(ui_version or "").strip(),
        "profile": clean_profile,
        "route": str(route or "").strip() or "auto",
        "href": str(href or "").strip(),
        "host": clean_host,
        "source_ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
        "seen_at": now_iso,
        "seen_ts": now_ts,
    }
    with _console_heartbeats_lock:
        _prune_console_heartbeats(now_ts)
        _console_heartbeats[key] = payload
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@app_routes.get("/api/console-ui/heartbeats")
async def console_ui_heartbeats(
    _: User = Depends(get_current_user),
):
    now_ts, _ = _console_heartbeat_now()
    with _console_heartbeats_lock:
        _prune_console_heartbeats(now_ts)
        items = sorted(
            _console_heartbeats.values(),
            key=lambda item: float(item.get("seen_ts") or 0),
            reverse=True,
        )
    return {"items": items, "count": len(items)}


def clear_access_token_cookie(response: Response):
    response.delete_cookie("access_token")
    return response


@app_routes.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(current_dir, "static/favicon.ico"))


@app_routes.get("/")
async def home_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return RedirectResponse(url=_norman_chat_redirect_url(request), status_code=307)


@app_routes.get("/index.html")
async def index_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return await home(request, db)


@app_routes.get("/dashboard")
async def dashboard_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return await home(request, db)


@app_routes.get("/dashboard.html")
async def dashboard_html_endpoint(
    request: Request, db: Session = Depends(get_async_db)
):
    return await home(request, db)


@app_routes.get("/switchboard")
async def switchboard_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return RedirectResponse(url="/dashboard.html?view=switchboard", status_code=307)


@app_routes.get("/switchboard.html")
async def switchboard_html_endpoint(
    request: Request, db: Session = Depends(get_async_db)
):
    return RedirectResponse(url="/dashboard.html?view=switchboard", status_code=307)


@app_routes.get("/connectors.html")
async def connectors_endpoint(request: Request):
    return await connectors(request)


@app_routes.get("/filters.html")
async def filters_endpoint(request: Request):
    return await filters(request)


@app_routes.get("/actions.html")
async def actions_endpoint(request: Request):
    from app.views import actions

    return await actions(request)


@app_routes.get("/channels.html")
async def channels_endpoint(request: Request):
    return await channels(request)


@app_routes.get("/bots.html")
async def bots_endpoint(request: Request):
    return await bots(request)


@app_routes.get("/systems.html")
async def systems_endpoint(request: Request):
    return await systems(request)


@app_routes.get("/messages_log.html")
async def messages_endpoint(request: Request):
    return await messages(request)


@app_routes.get("/editor")
async def editor_endpoint(request: Request):
    return await messages(request)


@app_routes.get("/editor.html")
async def editor_html_endpoint(request: Request):
    return await messages(request)


@app_routes.get("/consoles.html")
async def consoles_endpoint(request: Request):
    return await consoles(request)


@app_routes.get("/captions.html")
async def captions_endpoint(request: Request):
    return await captions(request)


@app_routes.get("/api/captions")
async def captions_api():
    return []


@app_routes.get("/quickstart.html")
async def quickstart_endpoint(request: Request):
    return await quickstart(request)


@app_routes.post("/api/bots/create")
async def create_bot_endpoint(
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    form_data = await request.json()
    bot = BotCreate(**form_data)
    bot = create_bot(db=db, bot_create=bot, user_id=current_user.id)
    return JSONResponse(
        content={
            "id": bot.id,
            "name": bot.name,
            "description": bot.description,
            "gpt_model": bot.gpt_model,
        }
    )


@app_routes.get("/api/bots", response_model=List[BotOut])
async def get_bots_endpoint(
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    try:
        bots = get_bots_by_user_id(db, current_user.id)
        bot_outs = [
            BotOut.from_orm(bot) for bot in bots
        ]  # Convert the list of Bot objects to a list of BotOut instances
        bot_dicts = [
            bot_out.dict() for bot_out in bot_outs
        ]  # Convert the list of BotOut instances to a list of dictionaries
        return JSONResponse(
            content=bot_dicts
        )  # Return the list of dictionaries as a JSONResponse
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail="An error occurred while fetching bots"
        )


@app_routes.get("/api/bots/default", response_model=BotOut)
async def get_default_bot_endpoint(
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    bots = get_bots_by_user_id(db, current_user.id)
    if not bots:
        raise HTTPException(status_code=404, detail="No bots found")
    welcome = next((bot for bot in bots if bot.name == "Welcome Bot"), None)
    bot = welcome or bots[0]
    return BotOut.from_orm(bot).dict()


@app_routes.delete("/api/bots/{bot_id}")
async def delete_bot_endpoint(
    bot_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_bot_or_404(db, bot_id, current_user)
    try:
        from app.crud.interaction import delete_interactions_by_bot_id
        from app.models.routing import RoutingEvent, RoutingJob, RoutingRule

        delete_interactions_by_bot_id(db=db, bot_id=bot_id)
        delete_messages_by_bot_id(db=db, bot_id=bot_id)
        event_ids = [
            event_id
            for (event_id,) in db.query(RoutingEvent.id)
            .filter(RoutingEvent.bot_id == bot_id)
            .all()
        ]
        if event_ids:
            db.query(RoutingJob).filter(RoutingJob.event_id.in_(event_ids)).delete(
                synchronize_session=False
            )
        db.query(RoutingEvent).filter(RoutingEvent.bot_id == bot_id).delete(
            synchronize_session=False
        )
        db.query(RoutingRule).filter(RoutingRule.bot_id == bot_id).delete(
            synchronize_session=False
        )
        db.commit()
        success = delete_bot(db=db, bot_id=bot_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Bot has related records. Remove interactions/messages first.",
        )

    if success:
        return {"status": "success", "message": "Bot deleted successfully"}
    return {"status": "error", "message": "Failed to delete bot"}


@app_routes.get("/api/bots/{bot_id}", response_model=BotOut)
async def get_bot_endpoint(
    bot_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    bot = _get_user_bot_or_404(db, bot_id, current_user)
    return BotOut.from_orm(bot).dict()


@app_routes.put("/api/bots/{bot_id}")
async def update_bot_endpoint(
    bot_id: int,
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_bot_or_404(db, bot_id, current_user)
    data = await request.json()
    bot_data = BotUpdate(**data)
    updated = update_bot(db=db, bot_id=bot_id, bot_data=bot_data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return BotOut.from_orm(updated).dict()


@app_routes.get("/api/bots/{bot_id}/messages", response_model=List[Message])
async def get_messages_endpoint(
    bot_id: int,
    limit: int = 100,
    offset: int = 0,
    cursor: Optional[int] = None,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Return messages for a bot with optional pagination."""
    try:
        _get_user_bot_or_404(db, bot_id, current_user)
        cursor_int = cursor
        messages = get_messages_by_bot_id(
            db=db, bot_id=bot_id, limit=limit, offset=offset, cursor=cursor_int
        )
        return [Message.from_orm(message).dict() for message in messages]
    except Exception:
        logger.exception("Failed to fetch messages")
        raise HTTPException(status_code=500, detail="Failed to fetch messages")


@app_routes.get("/api/bots/{bot_id}/messages/{message_id}", response_model=Message)
async def get_message_endpoint(
    bot_id: int,
    message_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    message = _get_user_message_or_404(db, bot_id, message_id, current_user)
    return Message.from_orm(message).dict()


@app_routes.post("/api/bots/{bot_id}/messages")
async def create_message_endpoint(
    bot_id: int,
    request: Request,
    history_limit: int = 10,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _get_user_bot_or_404(db, bot_id, current_user)
        ljson = await request.json()
        user_text = ljson.get("content")
        from app.core.hooks import run_pre_hooks, run_post_hooks

        user_text, hook_ctx = await run_pre_hooks(user_text, {"bot_id": bot_id})
        message = create_message(db=db, bot_id=bot_id, text=user_text, source="user")

        # get the last messages for this bot, so it can generate a response based on history
        last_messages = get_last_messages_by_bot_id(
            db=db, bot_id=bot_id, limit=history_limit
        )

        bot = get_bot_by_id(db=db, bot_id=bot_id)

        # Create a chat interaction with OpenAI
        # Create the messages array to be sent to the OpenAI API
        messages = [{"role": "system", "content": bot.system_prompt}]
        for msg in reversed(last_messages):
            messages.append({"role": msg.source, "content": msg.text})

        # count the tokens and ensure we do not exceed the bot.default_prompt_tokens
        def token_count(msgs):
            return sum(len(m["content"].split()) for m in msgs)

        while token_count(messages) > bot.default_prompt_tokens and len(messages) > 1:
            # remove the oldest user/assistant message
            messages.pop(1)

        try:
            interaction_response = await create_chat_interaction(
                model=bot.gpt_model,
                messages=messages,
                max_tokens=bot.default_response_tokens,
            )
        except APIError as exc:
            logger.error("OpenAI interaction failed: %s", exc)
            return {"status": "error", "message": str(exc)}

        assistant_text = interaction_response["choices"][0]["message"]["content"]
        assistant_text, hook_ctx = await run_post_hooks(assistant_text, hook_ctx)

        # Create an interaction schema
        interaction_in = InteractionCreate(
            bot_id=bot_id,
            message_id=message.id,
            input_data=message.text,
            gpt_model=interaction_response["model"],
            output_data=assistant_text,
            tokens_in=interaction_response["usage"]["prompt_tokens"],
            tokens_out=interaction_response.get("usage", {}).get(
                "completion_tokens", 0
            ),
            status_code=200,
            headers=str(interaction_response.get("headers", {})),
        )

        # Create a new interaction in the database
        interaction = create_interaction(db=db, interaction=interaction_in)
        message = create_message(
            db=db, bot_id=bot_id, text=assistant_text, source="assistant"
        )
        return {
            "status": "success",
            "message": "Message and interaction created successfully",
            "data": {"message": message, "interaction": interaction},
        }
    except Exception as e:
        logger.exception("Failed to create message and interaction")
        return {
            "status": "error",
            "message": "Failed to create message and interaction",
        }


@app_routes.put("/api/bots/{bot_id}/messages/{message_id}", response_model=Message)
async def update_message_endpoint(
    bot_id: int,
    message_id: int,
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_message_or_404(db, bot_id, message_id, current_user)
    payload = await request.json()
    message_data = MessageUpdate(**payload)
    if not message_data.text:
        raise HTTPException(status_code=400, detail="Message text is required")
    updated = update_message(db=db, message_id=message_id, text=message_data.text)
    if updated is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return Message.from_orm(updated).dict()


@app_routes.delete("/api/bots/{bot_id}/messages/{message_id}")
async def delete_message_endpoint(
    bot_id: int,
    message_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_message_or_404(db, bot_id, message_id, current_user)
    delete_message(db=db, message_id=message_id)
    return {"status": "success"}


@app_routes.post("/api/connectors/create")
async def create_connector_endpoint(
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    data = await request.json()
    connector_in = ConnectorCreate(**data)
    if connector_in.connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")
    connector = connector_crud.create(db, obj_in=connector_in, user_id=current_user.id)
    return JSONResponse(content=Connector.from_orm(connector).dict())


@app_routes.get("/api/connectors", response_model=List[Connector])
async def get_connectors_endpoint(
    response: Response,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=30"
    connectors = connector_crud.get_multi_by_user(db, current_user.id)
    return [Connector.from_orm(c).dict() for c in connectors]


@app_routes.get("/api/connectors/{connector_id}", response_model=Connector)
async def get_connector_endpoint(
    connector_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    return Connector.from_orm(connector).dict()


@app_routes.put("/api/connectors/{connector_id}", response_model=Connector)
async def update_connector_endpoint(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    data = await request.json()
    connector_type = data.get("connector_type")
    if connector_type and connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    updated = connector_crud.update(
        db, db_obj=connector, obj_in=ConnectorUpdate(**data)
    )
    return Connector.from_orm(updated).dict()


@app_routes.delete("/api/connectors/{connector_id}")
async def delete_connector_endpoint(
    connector_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_connector_or_404(db, connector_id, current_user)
    try:
        connector_crud.remove(db, connector_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Connector has related channels. Remove channels first.",
        )
    return {"status": "success"}


@app_routes.post("/api/connectors/{connector_id}/test")
async def test_connector_endpoint(
    connector_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    instance = get_connector(connector.connector_type, connector.config or {})
    status_value = "up" if instance.is_connected() else "down"
    return {"status": status_value}


@app_routes.post("/api/connectors/{connector_id}/webhook")
async def set_connector_webhook_endpoint(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    payload = await request.json()
    webhook_url = payload.get("url")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")

    instance = get_connector(connector.connector_type, connector.config or {})
    setter = getattr(instance, "set_webhook", None)
    if setter is None:
        raise HTTPException(
            status_code=400,
            detail="Connector does not support webhook setup",
        )
    result = setter(webhook_url)
    if hasattr(result, "__await__"):
        result = await result
    return {"status": "success" if result else "error"}


@app_routes.get("/api/connectors/{connector_id}/status")
async def connector_status_endpoint(
    connector_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    config = connector.config or {}
    if connector.connector_type == "webhook" and not config.get("webhook_url"):
        status_value = "missing_config"
    else:
        try:
            instance = get_connector(connector.connector_type, config)
            status_value = "up" if instance.is_connected() else "down"
        except Exception as exc:
            logger.warning("Connector %s status failed: %s", connector.id, exc)
            status_value = "missing_config"
    return {
        "status": status_value,
        "last_message_sent": (
            connector.last_message_sent.isoformat()
            if connector.last_message_sent
            else None
        ),
        "last_message_received": (
            connector.last_message_received.isoformat()
            if connector.last_message_received
            else None
        ),
        "last_successful_message": (
            connector.last_successful_message.isoformat()
            if connector.last_successful_message
            else None
        ),
    }


@app_routes.get("/api/connectors/{connector_id}/diagnose")
async def connector_diagnose_endpoint(
    connector_id: int,
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    diagnosis = _build_connector_diagnosis(connector)
    diagnosis.update(
        {
            "connector_id": connector.id,
            "connector_type": connector.connector_type,
            "connector_name": connector.name,
        }
    )
    return diagnosis


@app_routes.post("/token", response_model=Token)
async def token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_async_db),
):
    user_auth = UserAuthenticate(email=form_data.username, password=form_data.password)
    user = authenticate_user(db, user_auth)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@app_routes.get("/login.html")
async def login_endpoint(request: Request):
    return await login(request)


@app_routes.get("/setup.html")
async def setup_endpoint(request: Request):
    return await setup(request)


@app_routes.get("/settings.html")
async def settings_endpoint(
    request: Request, current_user: User = Depends(get_current_user)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    return await settings_page(request, bool(settings.openai_api_key))


@app_routes.post("/settings/openai")
async def update_openai_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    key = (form.get("openai_api_key") or "").strip()
    if not key:
        return RedirectResponse(
            url="/settings.html?status=warning&message=API%20key%20is%20required",
            status_code=303,
        )

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )
    cfg["openai_api_key"] = key
    _save_config(cfg)

    settings.openai_api_key = key
    return RedirectResponse(
        url="/settings.html?status=success&message=OpenAI%20key%20saved",
        status_code=303,
    )


@app_routes.post("/settings/theme")
async def update_theme_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    theme = (form.get("ui_theme") or "").strip()
    if not theme:
        return RedirectResponse(
            url="/settings.html?status=warning&message=Theme%20required",
            status_code=303,
        )
    if theme not in settings.ui_available_themes:
        return RedirectResponse(
            url="/settings.html?status=warning&message=Theme%20not%20recognized",
            status_code=303,
        )

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )
    cfg["ui_theme"] = theme
    _save_config(cfg)

    settings.ui_theme = theme
    return RedirectResponse(
        url="/settings.html?status=success&message=Theme%20saved",
        status_code=303,
    )


def _load_config():
    config_path = active_config_file_path()
    if config_path is None or not config_path.exists():
        raise FileNotFoundError("config.yaml not found")
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict):
    config_path = active_config_file_path()
    if config_path is None:
        raise FileNotFoundError("config.yaml not found")
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)


def _lock_all_tmux_connectors_for_failsafe(reason: str) -> int:
    """Best-effort lock of every tmux connector when hard kill is enabled."""
    changed = 0
    db = db_session.SessionLocal()
    try:
        connectors = (
            db.query(models.Connector)
            .filter(models.Connector.connector_type == "tmux")
            .all()
        )
        for connector in connectors:
            cfg = dict(connector.config or {})
            if (
                bool(cfg.get("locked"))
                and str(cfg.get("locked_reason") or "") == reason
            ):
                continue
            cfg["locked"] = True
            cfg["locked_reason"] = reason
            connector.config = cfg
            db.add(connector)
            changed += 1
        if changed:
            db.commit()
        else:
            db.rollback()
        return changed
    finally:
        db.close()


def _safety_status_payload(current_user: Optional[User] = None) -> Dict[str, object]:
    level = int(current_kill_switch_level(settings))
    return {
        "kill_switch_level": level,
        "kill_switch_label": kill_switch_label(level),
        "execution_enabled": bool(getattr(settings, "safety_execution_enabled", True)),
        "read_only": bool(getattr(settings, "safety_read_only", False)),
        "effective_read_only": bool(effective_read_only(settings)),
        "execution_blocked_reason": execution_blocked_reason(settings),
        "tmux_commands_block_reason": tmux_commands_block_reason(settings),
        "routing_actions_block_reason": routing_actions_block_reason(settings),
        "can_panic": bool(getattr(current_user, "is_superuser", False)),
    }


_ALLOWED_IMAGE_TYPES: Dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _user_media_dir() -> str:
    return os.path.join(current_dir, "static", "user_media")


def _delete_user_media_variants(target: str) -> None:
    media_dir = _user_media_dir()
    for ext in set(_ALLOWED_IMAGE_TYPES.values()):
        candidate = os.path.join(media_dir, f"{target}.{ext}")
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                logger.warning("Failed deleting user media file: %s", candidate)


async def _save_upload_limited(upload: UploadFile, dest_path: str) -> int:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    total = 0
    with open(dest_path, "wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload too large")
            out.write(chunk)
    return total


@app_routes.post("/settings/api-keys")
async def update_api_keys(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    form = await request.form()
    mcp_api_url = (form.get("mcp_api_url") or "").strip()
    mcp_api_key = (form.get("mcp_api_key") or "").strip()
    openai_default_model = (form.get("openai_default_model") or "").strip()
    openai_max_tokens = (form.get("openai_max_tokens") or "").strip()

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    cfg["mcp_api_url"] = mcp_api_url
    cfg["mcp_api_key"] = mcp_api_key
    if openai_default_model:
        cfg["openai_default_model"] = openai_default_model
        settings.openai_default_model = openai_default_model
    if openai_max_tokens:
        try:
            cfg["openai_max_tokens"] = int(openai_max_tokens)
            settings.openai_max_tokens = int(openai_max_tokens)
        except ValueError:
            return RedirectResponse(
                url="/settings.html?status=warning&message=Invalid%20max%20tokens",
                status_code=303,
            )

    _save_config(cfg)
    settings.mcp_api_url = mcp_api_url
    settings.mcp_api_key = mcp_api_key
    return RedirectResponse(
        url="/settings.html?status=success&message=API%20keys%20saved",
        status_code=303,
    )


@app_routes.post("/settings/sso")
async def update_sso_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    google_client_id = (form.get("google_client_id") or "").strip()
    google_client_secret = (form.get("google_client_secret") or "").strip()
    microsoft_client_id = (form.get("microsoft_client_id") or "").strip()
    microsoft_client_secret = (form.get("microsoft_client_secret") or "").strip()

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    if google_client_id:
        cfg["google_client_id"] = google_client_id
        settings.google_client_id = google_client_id
    if google_client_secret:
        cfg["google_client_secret"] = google_client_secret
        settings.google_client_secret = google_client_secret

    if microsoft_client_id:
        cfg["microsoft_client_id"] = microsoft_client_id
        settings.microsoft_client_id = microsoft_client_id
    if microsoft_client_secret:
        cfg["microsoft_client_secret"] = microsoft_client_secret
        settings.microsoft_client_secret = microsoft_client_secret

    _save_config(cfg)
    return RedirectResponse(
        url="/settings.html?status=success&message=SSO%20settings%20saved",
        status_code=303,
    )


@app_routes.post("/settings/safety")
async def update_safety_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    execution_enabled = form.get("safety_execution_enabled") == "on"
    read_only = form.get("safety_read_only") == "on"
    routing_ingest_only = form.get("routing_ingest_only") == "on"
    provenance_enforce = form.get("safety_provenance_enforce") == "on"
    shadow_rules_default = form.get("safety_shadow_rules_default") == "on"
    watchdog_autolock = form.get("safety_tmux_watchdog_autolock") == "on"
    budget_autolock = form.get("safety_budget_autolock") == "on"
    kill_switch_level = clamp_kill_switch_level(form.get("safety_kill_switch_level", 0))
    budget_per_minute_raw = str(form.get("safety_budget_default_per_minute") or "0")
    budget_per_hour_raw = str(form.get("safety_budget_default_per_hour") or "0")
    try:
        budget_per_minute = max(0, int(budget_per_minute_raw))
        budget_per_hour = max(0, int(budget_per_hour_raw))
    except ValueError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=Invalid%20budget%20value",
            status_code=303,
        )
    default_tmux_mode = (form.get("safety_default_tmux_mode") or "chat").strip().lower()
    if default_tmux_mode not in {"chat", "shell"}:
        default_tmux_mode = "chat"

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    cfg["safety_execution_enabled"] = bool(execution_enabled)
    cfg["safety_read_only"] = bool(read_only)
    cfg["routing_ingest_only"] = bool(routing_ingest_only)
    cfg["safety_default_tmux_mode"] = default_tmux_mode
    cfg["safety_kill_switch_level"] = int(kill_switch_level)
    cfg["safety_provenance_enforce"] = bool(provenance_enforce)
    cfg["safety_shadow_rules_default"] = bool(shadow_rules_default)
    cfg["safety_tmux_watchdog_autolock"] = bool(watchdog_autolock)
    cfg["safety_budget_default_per_minute"] = int(budget_per_minute)
    cfg["safety_budget_default_per_hour"] = int(budget_per_hour)
    cfg["safety_budget_autolock"] = bool(budget_autolock)
    _save_config(cfg)

    settings.safety_execution_enabled = bool(execution_enabled)
    settings.safety_read_only = bool(read_only)
    settings.routing_ingest_only = bool(routing_ingest_only)
    settings.safety_default_tmux_mode = default_tmux_mode
    settings.safety_kill_switch_level = int(kill_switch_level)
    settings.safety_provenance_enforce = bool(provenance_enforce)
    settings.safety_shadow_rules_default = bool(shadow_rules_default)
    settings.safety_tmux_watchdog_autolock = bool(watchdog_autolock)
    settings.safety_budget_default_per_minute = int(budget_per_minute)
    settings.safety_budget_default_per_hour = int(budget_per_hour)
    settings.safety_budget_autolock = bool(budget_autolock)

    if int(kill_switch_level) >= 5:
        _lock_all_tmux_connectors_for_failsafe("kill-switch-hard-kill")

    return RedirectResponse(
        url="/settings.html?status=success&message=Safety%20settings%20saved",
        status_code=303,
    )


@app_routes.get("/api/v1/safety/status")
async def get_safety_status(
    current_user: User = Depends(get_current_user),
):
    return JSONResponse(content=_safety_status_payload(current_user))


@app_routes.get("/api/llm/status")
async def get_llm_status(
    current_user: User = Depends(get_current_user),
):
    if get_llm_runtime_status is None:
        raise HTTPException(
            status_code=503,
            detail="LLM runtime status is unavailable on this host",
        )
    payload = get_llm_runtime_status()
    if get_mesh_overview is not None:
        payload = dict(payload)
        payload["norllama_mesh"] = get_mesh_overview(timeout_seconds=2)
        if build_warm_policy is not None:
            payload["norllama_warm_policy"] = build_warm_policy(
                mesh=payload["norllama_mesh"]
            )
    if fetch_tool_activity is not None:
        payload = dict(payload)
        try:
            payload["norllama_tool_activity"] = fetch_tool_activity(
                limit=200,
                timeout_seconds=2,
            )
        except Exception as exc:
            payload["norllama_tool_activity"] = {
                "schema": "norman.norllama.tool-activity.v1",
                "provider": "norllama",
                "status": "error",
                "tool_call_count": 0,
                "capability_counts": {},
                "latest_tool_call": {},
                "items": [],
                "error": str(exc)[:240],
            }
    return JSONResponse(content=payload)


@app_routes.get("/api/llm/mesh")
async def get_llm_mesh(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if get_mesh_overview is None:
        raise HTTPException(
            status_code=503,
            detail="Norllama mesh overview is unavailable on this host",
        )
    refresh = str(request.query_params.get("refresh") or "").lower() in {
        "1",
        "true",
        "yes",
        "force",
    }
    return JSONResponse(
        content=get_mesh_overview(force_refresh=refresh, timeout_seconds=2)
    )


@app_routes.get("/api/llm/warm-policy")
async def get_llm_warm_policy(
    current_user: User = Depends(get_current_user),
):
    if build_warm_policy is None:
        raise HTTPException(
            status_code=503,
            detail="Norllama warm policy is unavailable on this host",
        )
    return JSONResponse(content=build_warm_policy())


@app_routes.get("/api/llm/tool-activity")
async def get_llm_tool_activity(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if fetch_tool_activity is None:
        raise HTTPException(
            status_code=503,
            detail="Norllama tool activity is unavailable on this host",
        )
    try:
        limit = int(request.query_params.get("limit") or 200)
    except ValueError:
        limit = 200
    try:
        payload = fetch_tool_activity(
            limit=max(1, min(limit, 1000)),
            timeout_seconds=2,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Norllama tool activity is unavailable: {str(exc)[:200]}",
        ) from exc
    return JSONResponse(content=payload)


@app_routes.post("/api/llm/warm-policy/prefetch")
async def post_llm_warm_policy_prefetch(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if apply_warm_policy is None:
        raise HTTPException(
            status_code=503,
            detail="Norllama warm policy is unavailable on this host",
        )
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    dry_run = bool(body.get("dry_run", True))
    prefetch_limit = body.get("prefetch_limit")
    try:
        limit = int(prefetch_limit) if prefetch_limit is not None else None
    except (TypeError, ValueError):
        limit = None
    priority = str(body.get("priority") or "background").strip() or "background"
    return JSONResponse(
        content=apply_warm_policy(
            dry_run=dry_run,
            prefetch_limit=limit,
            priority=priority,
        )
    )


@app_routes.get("/api/llm/ping/targets")
async def get_llm_ping_targets(
    current_user: User = Depends(get_current_user),
):
    if list_model_ping_targets is None:
        raise HTTPException(
            status_code=503,
            detail="Model ping targets are unavailable on this host",
        )
    return JSONResponse(content={"items": list_model_ping_targets()})


@app_routes.post("/api/llm/ping")
async def post_llm_ping(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if ping_model_targets is None:
        raise HTTPException(
            status_code=503,
            detail="Model ping is unavailable on this host",
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target_id = ""
    if isinstance(payload, dict):
        target_id = str(payload.get("target_id") or payload.get("target") or "").strip()
    try:
        return JSONResponse(content=await ping_model_targets(target_id=target_id))
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Model ping target not found"
        ) from exc


@app_routes.post("/api/v1/safety/panic")
async def trigger_safety_panic(
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        settings.safety_kill_switch_level = 5
    except Exception:
        # Older in-memory settings objects may not expose safety fields yet.
        pass
    persisted = False
    try:
        cfg = _load_config()
        cfg["safety_kill_switch_level"] = 5
        _save_config(cfg)
        persisted = True
    except FileNotFoundError:
        persisted = False

    locked = _lock_all_tmux_connectors_for_failsafe("kill-switch-hard-kill")
    payload = _safety_status_payload(current_user)
    payload.update(
        {
            "status": "ok",
            "persisted": persisted,
            "locked_connectors": int(locked),
        }
    )
    return JSONResponse(content=payload)


@app_routes.post("/settings/background/upload")
async def upload_background_asset(
    current_user: User = Depends(get_current_user),
    target: str = Form("background"),
    file: UploadFile = File(...),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    target = (target or "").strip().lower()
    if target not in {"background", "titlebar"}:
        raise HTTPException(status_code=400, detail="Invalid target")

    content_type = (file.content_type or "").strip().lower()
    ext = _ALLOWED_IMAGE_TYPES.get(content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    media_dir = _user_media_dir()
    dest_path = os.path.join(media_dir, f"{target}.{ext}")

    # Keep a single canonical file per target to avoid confusion and stale content.
    _delete_user_media_variants(target)
    await _save_upload_limited(file, dest_path)

    cache_bust = uuid.uuid4().hex[:10]
    url = f"/static/user_media/{target}.{ext}?v={cache_bust}"

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    if target == "background":
        cfg["ui_background_image_url"] = url
        settings.ui_background_image_url = url
    else:
        cfg["ui_titlebar_image_url"] = url
        settings.ui_titlebar_image_url = url

    _save_config(cfg)
    return RedirectResponse(
        url="/settings.html?status=success&message=Image%20uploaded",
        status_code=303,
    )


@app_routes.post("/settings/background/ambient")
async def update_ambient_backgrounds(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    enabled = form.get("ui_ambient_backgrounds") == "on"

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    cfg["ui_ambient_backgrounds"] = enabled
    _save_config(cfg)
    settings.ui_ambient_backgrounds = enabled
    return RedirectResponse(
        url="/settings.html?status=success&message=Ambient%20backgrounds%20saved",
        status_code=303,
    )


@app_routes.post("/settings/background/clear")
async def clear_background_asset(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    form = await request.form()
    target = (form.get("target") or "").strip().lower()
    if target not in {"background", "titlebar"}:
        return RedirectResponse(
            url="/settings.html?status=warning&message=Invalid%20target",
            status_code=303,
        )

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    if target == "background":
        cfg["ui_background_image_url"] = ""
        settings.ui_background_image_url = ""
    else:
        cfg["ui_titlebar_image_url"] = ""
        settings.ui_titlebar_image_url = ""
    _save_config(cfg)

    _delete_user_media_variants(target)
    return RedirectResponse(
        url="/settings.html?status=success&message=Image%20cleared",
        status_code=303,
    )


@app_routes.post("/settings/notifications")
async def update_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    form = await request.form()
    notify_email_enabled = form.get("notify_email_enabled") == "on"
    notify_email_to = (form.get("notify_email_to") or "").strip()
    notify_webhook_enabled = form.get("notify_webhook_enabled") == "on"
    notify_webhook_url = (form.get("notify_webhook_url") or "").strip()
    notify_digest_frequency = (form.get("notify_digest_frequency") or "daily").strip()

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    cfg["notify_email_enabled"] = notify_email_enabled
    cfg["notify_email_to"] = notify_email_to
    cfg["notify_webhook_enabled"] = notify_webhook_enabled
    cfg["notify_webhook_url"] = notify_webhook_url
    cfg["notify_digest_frequency"] = notify_digest_frequency
    _save_config(cfg)

    settings.notify_email_enabled = notify_email_enabled
    settings.notify_email_to = notify_email_to
    settings.notify_webhook_enabled = notify_webhook_enabled
    settings.notify_webhook_url = notify_webhook_url
    settings.notify_digest_frequency = notify_digest_frequency
    return RedirectResponse(
        url="/settings.html?status=success&message=Notification%20settings%20saved",
        status_code=303,
    )


@app_routes.post("/settings/notifications/test")
async def test_notifications(
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    # This uses the global webhook notification settings, and is intended to
    # validate phone-first notification plumbing.
    from app.services.notifications import maybe_notify_webhook

    await maybe_notify_webhook(
        event_type="notifications.test",
        payload={
            "message": "Norman test notification",
            "hint": "If you see this on your phone, approvals can alert you.",
            "link": "/connectors.html?panel=approvals",
        },
    )

    return RedirectResponse(
        url="/settings.html?status=success&message=Test%20notification%20sent",
        status_code=303,
    )


@app_routes.post("/settings/connectors")
async def update_connector_defaults(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    form = await request.form()
    default_language = (form.get("connector_default_language") or "en").strip()
    default_channel = (form.get("connector_default_channel") or "").strip()
    retry_attempts = (form.get("connector_retry_attempts") or "").strip()
    timeout_seconds = (form.get("connector_timeout_seconds") or "").strip()

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    cfg["connector_default_language"] = default_language
    cfg["connector_default_channel"] = default_channel
    if retry_attempts:
        try:
            cfg["connector_retry_attempts"] = int(retry_attempts)
        except ValueError:
            return RedirectResponse(
                url="/settings.html?status=warning&message=Invalid%20retry%20attempts",
                status_code=303,
            )
    if timeout_seconds:
        try:
            cfg["connector_timeout_seconds"] = int(timeout_seconds)
        except ValueError:
            return RedirectResponse(
                url="/settings.html?status=warning&message=Invalid%20timeout",
                status_code=303,
            )

    _save_config(cfg)
    settings.connector_default_language = default_language
    settings.connector_default_channel = default_channel
    if retry_attempts:
        settings.connector_retry_attempts = int(retry_attempts)
    if timeout_seconds:
        settings.connector_timeout_seconds = int(timeout_seconds)
    return RedirectResponse(
        url="/settings.html?status=success&message=Connector%20defaults%20saved",
        status_code=303,
    )


@app_routes.post("/settings/performance")
async def update_performance_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    form = await request.form()
    rate_limit_requests = (form.get("rate_limit_requests") or "").strip()
    rate_limit_window_seconds = (form.get("rate_limit_window_seconds") or "").strip()
    cache_ttl_seconds = (form.get("cache_ttl_seconds") or "").strip()
    database_pool_size = (form.get("database_pool_size") or "").strip()
    database_max_overflow = (form.get("database_max_overflow") or "").strip()

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=config.yaml%20not%20found",
            status_code=303,
        )

    try:
        if rate_limit_requests:
            cfg["rate_limit_requests"] = int(rate_limit_requests)
            settings.rate_limit_requests = int(rate_limit_requests)
        if rate_limit_window_seconds:
            cfg["rate_limit_window_seconds"] = int(rate_limit_window_seconds)
            settings.rate_limit_window_seconds = int(rate_limit_window_seconds)
        if cache_ttl_seconds:
            cfg["cache_ttl_seconds"] = int(cache_ttl_seconds)
            settings.cache_ttl_seconds = int(cache_ttl_seconds)
        if database_pool_size:
            cfg["database_pool_size"] = int(database_pool_size)
            settings.database_pool_size = int(database_pool_size)
        if database_max_overflow:
            cfg["database_max_overflow"] = int(database_max_overflow)
            settings.database_max_overflow = int(database_max_overflow)
    except ValueError:
        return RedirectResponse(
            url="/settings.html?status=warning&message=Invalid%20performance%20value",
            status_code=303,
        )

    _save_config(cfg)
    return RedirectResponse(
        url="/settings.html?status=success&message=Performance%20settings%20saved",
        status_code=303,
    )


@app_routes.post("/setup", response_class=HTMLResponse)
async def setup_post(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_async_db),
):
    key = request.query_params.get("key")
    if not key:
        form = await request.form()
        key = form.get("setup_key")
    if key != settings.admin_setup_key:
        raise HTTPException(status_code=401, detail="Invalid setup key")

    if is_admin_user_exists(db):
        return RedirectResponse(url="/login.html", status_code=303)

    user = create_admin_user(
        db,
        email=form_data.username,
        password=form_data.password,
        username=form_data.username.split("@")[0],
    )
    _bootstrap_user_workspace(db, user)
    response = _set_login_cookie(user.email)
    return response


@app_routes.get("/logout", response_class=HTMLResponse)
async def logout_endpoint(request: Request, response: Response):
    clear_access_token_cookie(response)
    return await logout(request)


# @app_routes.post("/login", response_class=HTMLResponse)
# async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
#    user = await authenticate_user(form_data.username, form_data.password)


@app_routes.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_async_db),
):
    user_auth = UserAuthenticate(email=form_data.username, password=form_data.password)
    user = authenticate_user(db, user_auth)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    _bootstrap_user_workspace(db, user)

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        samesite="lax",
        path="/",
    )
    return response


def _random_password() -> str:
    """Generate a random password for new SSO users."""
    return uuid.uuid4().hex


def _bootstrap_user_workspace(db: Session, user: User) -> None:
    """Ensure first-login users have a working bot and connector."""
    try:
        existing_bot = (
            db.query(models.Bot).filter(models.Bot.user_id == user.id).first()
        )
        bot_for_default = existing_bot
        if not existing_bot:
            default_model = (
                settings.openai_available_models[0]
                if settings.openai_available_models
                else settings.openai_default_model or "gpt-5.5"
            )
            bot_for_default = create_bot(
                db=db,
                bot_create=BotCreate(
                    name="Welcome Bot",
                    description="Starter assistant to help you test Norman.",
                    gpt_model=default_model,
                ),
                user_id=user.id,
            )
            create_message(
                db=db,
                bot_id=bot_for_default.id,
                text=(
                    "Welcome to Norman! Send a message to this bot to verify the "
                    "platform is working."
                ),
                source="assistant",
            )

        existing_connectors = connector_crud.get_multi_by_user(
            db, user_id=user.id, limit=1
        )
        if not existing_connectors:
            connector = connector_crud.create(
                db=db,
                obj_in=ConnectorCreate(
                    name="Webhook Inbox",
                    connector_type="webhook",
                    config={
                        "purpose": "inbound_demo",
                        "notes": "Use the webhook URL shown on the connectors page.",
                    },
                ),
                user_id=user.id,
            )
            if bot_for_default:
                routing_crud.create_rule(
                    db,
                    user_id=user.id,
                    rule_in=RoutingRuleCreate(
                        name="Default Webhook Route",
                        connector_id=connector.id,
                        connector_type="webhook",
                        bot_id=bot_for_default.id,
                        match_type="all",
                        priority=100,
                        is_active=True,
                    ),
                )
    except Exception:
        logger.exception("Failed to bootstrap workspace for user %s", user.id)


def _set_login_cookie(user_email: str) -> Response:
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user_email}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        samesite="lax",
        path="/",
    )
    return response


def _get_redirect_uri(request: Request, provider: str) -> str:
    return str(request.url_for(f"{provider}_callback"))


def _looks_like_placeholder(value: str) -> bool:
    """Detect config.yaml.dist placeholder values like 'your_google_client_id'."""
    value = (value or "").strip()
    return value.startswith("your_") or value in {"change_me", "change_me_setup_key"}


def _oauth_cookie_name(provider: str, kind: str) -> str:
    return f"oauth_{provider}_{kind}"


def _set_oauth_cookies(response: Response, provider: str, state: str, nonce: str):
    for kind, value in (("state", state), ("nonce", nonce)):
        response.set_cookie(
            key=_oauth_cookie_name(provider, kind),
            value=value,
            httponly=True,
            max_age=600,
            samesite="lax",
        )


def _clear_oauth_cookies(response: Response, provider: str):
    for kind in ("state", "nonce"):
        response.delete_cookie(_oauth_cookie_name(provider, kind))


def _require_oauth_cookie(request: Request, provider: str, kind: str) -> str:
    value = request.cookies.get(_oauth_cookie_name(provider, kind))
    if not value:
        raise HTTPException(status_code=400, detail=f"Missing OAuth {kind}")
    return value


def _verify_google_id_token(id_token: str, nonce: Optional[str]) -> Dict[str, str]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid id_token header") from exc

    jwks_resp = requests.get("https://www.googleapis.com/oauth2/v3/certs", timeout=10)
    jwks_resp.raise_for_status()
    jwks = jwks_resp.json()
    key_data = next(
        (k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")),
        None,
    )
    if not key_data:
        raise HTTPException(status_code=400, detail="Signing key not found")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
    try:
        payload = jwt.decode(
            id_token,
            key=public_key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=["accounts.google.com", "https://accounts.google.com"],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid id_token") from exc

    if nonce and payload.get("nonce") != nonce:
        raise HTTPException(status_code=400, detail="Invalid nonce")
    return payload


def _get_user_bot_or_404(db: Session, bot_id: int, current_user: User) -> models.Bot:
    bot = get_bot_by_id(db=db, bot_id=bot_id)
    if not bot or bot.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


def _get_user_message_or_404(
    db: Session, bot_id: int, message_id: int, current_user: User
) -> "models.Message":
    bot = _get_user_bot_or_404(db, bot_id, current_user)
    message = get_message_by_id(db, message_id)
    if not message or message.bot_id != bot.id:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _parse_epoch_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _connector_fields_and_defaults(connector_type: str):
    connector_cls = connector_classes.get(connector_type)
    if connector_cls is None:
        return [], [], {}

    signature = inspect.signature(connector_cls.__init__)
    fields = []
    required = []
    defaults = {}
    for param in signature.parameters.values():
        if param.name in {"self", "config"}:
            continue
        fields.append(param.name)
        if param.default is inspect._empty:
            required.append(param.name)
        elif param.default is not None and isinstance(
            param.default, (str, int, float, bool)
        ):
            defaults[param.name] = param.default
    return fields, required, defaults


def _build_connector_diagnosis(connector):
    config = connector.config or {}
    fields, required_fields, defaults = _connector_fields_and_defaults(
        connector.connector_type
    )
    missing_fields = [field for field in fields if config.get(field) in (None, "")]
    missing_required_fields = [
        field for field in required_fields if field in missing_fields
    ]

    oauth = oauth_capability(connector.connector_type)
    auth = None
    if oauth:
        provider = config.get("oauth_provider") or oauth.default_provider
        token_field = oauth.token_field
        expires_at = _parse_epoch_int(config.get("oauth_expires_at"))
        auth = {
            "provider": provider,
            "token_field": token_field,
            "connected": bool(provider and config.get(token_field)),
            "expires_at": expires_at,
            "scopes": config.get("oauth_scopes")
            or oauth.scopes_by_provider.get(provider, [])
            if provider and oauth.scopes_by_provider
            else config.get("oauth_scopes") or [],
        }

    connectivity = "unknown"
    error = None
    try:
        instance = get_connector(connector.connector_type, config)
        connectivity = "up" if instance.is_connected() else "down"
    except Exception as exc:  # pragma: no cover - defensive runtime branch
        connectivity = "error"
        error = str(exc)

    actions = []
    if missing_required_fields:
        actions.append("Fill required fields: " + ", ".join(missing_required_fields))
    if auth and not auth["connected"]:
        actions.append(
            f"Connect {connector.connector_type} using {auth['provider'] or 'SSO'}"
        )
    if connectivity in {"down", "error"}:
        actions.append(
            "Run Test, then verify credentials, endpoint, and network reachability"
        )
    if not actions:
        actions.append("No immediate issues detected")

    return {
        "status": connectivity,
        "error": error,
        "fields": fields,
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "missing_required_fields": missing_required_fields,
        "defaults": defaults,
        "auth": auth,
        "recommended_actions": actions,
    }


def _get_user_connector_or_404(
    db: Session, connector_id: int, current_user: User
) -> models.Connector:
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@app_routes.get("/auth/google/login")
async def google_login(request: Request):
    if (
        not settings.google_client_id
        or not settings.google_client_secret
        or _looks_like_placeholder(settings.google_client_id)
        or _looks_like_placeholder(settings.google_client_secret)
    ):
        raise HTTPException(status_code=500, detail="Google SSO is not configured")
    state = uuid.uuid4().hex
    nonce = uuid.uuid4().hex
    params = {
        "client_id": settings.google_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": _get_redirect_uri(request, "google"),
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
        "nonce": nonce,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    response = RedirectResponse(url)
    _set_oauth_cookies(response, "google", state, nonce)
    return response


@app_routes.get("/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_async_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        raise HTTPException(status_code=400, detail="Code not provided")
    expected_state = _require_oauth_cookie(request, "google", "state")
    nonce = _require_oauth_cookie(request, "google", "nonce")
    if not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": _get_redirect_uri(request, "google"),
        "grant_type": "authorization_code",
    }
    resp = requests.post("https://oauth2.googleapis.com/token", data=data)
    resp.raise_for_status()
    token_info = resp.json()
    id_token = token_info.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    user_info = _verify_google_id_token(id_token, nonce)
    email = user_info.get("email")
    username = user_info.get("name") or email
    if not email:
        raise HTTPException(status_code=400, detail="Email not available")
    user = get_user_by_email(db, email=email)
    if not user:
        user = create_user(
            db, UserCreate(email=email, username=username, password=_random_password())
        )
    _bootstrap_user_workspace(db, user)
    response = _set_login_cookie(user.email)
    _clear_oauth_cookies(response, "google")
    return response


@app_routes.get("/auth/microsoft/login")
async def microsoft_login(request: Request):
    if (
        not settings.microsoft_client_id
        or not settings.microsoft_client_secret
        or _looks_like_placeholder(settings.microsoft_client_id)
        or _looks_like_placeholder(settings.microsoft_client_secret)
    ):
        raise HTTPException(status_code=500, detail="Microsoft SSO is not configured")
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "scope": "https://graph.microsoft.com/user.read openid email profile",
        "redirect_uri": _get_redirect_uri(request, "microsoft"),
        "response_mode": "query",
    }
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urlencode(
        params
    )
    return RedirectResponse(url)


@app_routes.get("/auth/microsoft/callback")
async def microsoft_callback(request: Request, db: Session = Depends(get_async_db)):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code not provided")
    data = {
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret,
        "code": code,
        "redirect_uri": _get_redirect_uri(request, "microsoft"),
        "grant_type": "authorization_code",
        "scope": "https://graph.microsoft.com/user.read openid email profile",
    }
    resp = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token", data=data
    )
    resp.raise_for_status()
    token_info = resp.json()
    id_token = token_info.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    user_info = jwt.decode(id_token, options={"verify_signature": False})
    email = user_info.get("email") or user_info.get("preferred_username")
    username = user_info.get("name") or email
    if not email:
        raise HTTPException(status_code=400, detail="Email not available")
    user = get_user_by_email(db, email=email)
    if not user:
        user = create_user(
            db, UserCreate(email=email, username=username, password=_random_password())
        )
    _bootstrap_user_workspace(db, user)
    return _set_login_cookie(user.email)
