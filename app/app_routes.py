from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, Request, HTTPException
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
from app.core.config import settings
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

from datetime import timedelta
import os
import uuid
import requests
import jwt
import json
import yaml
from urllib.parse import urlencode
import traceback

from .views import (
    home,
    connectors,
    filters,
    channels,
    process_message,
    bots,
    messages,
    captions,
    login,
    logout,
    quickstart,
    setup,
    settings_page,
)
from app.connectors.connector_utils import get_connector, connector_classes
from app.schemas.connector import ConnectorCreate, ConnectorUpdate, Connector
from app import models

current_dir = os.path.dirname(os.path.realpath(__file__))
app_routes = APIRouter()
logger = setup_logger(__name__)


@app_routes.get("/health")
async def health() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


def clear_access_token_cookie(response: Response):
    response.delete_cookie("access_token")
    return response


@app_routes.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(current_dir, "static/favicon.ico"))


@app_routes.get("/")
async def home_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return await home(request, db)


@app_routes.get("/index.html")
async def index_endpoint(request: Request, db: Session = Depends(get_async_db)):
    return await home(request, db)


@app_routes.get("/connectors.html")
async def connectors_endpoint(request: Request):
    return await connectors(request)


@app_routes.get("/filters.html")
async def filters_endpoint(request: Request):
    return await filters(request)


@app_routes.get("/channels.html")
async def channels_endpoint(request: Request):
    return await channels(request)


@app_routes.get("/bots.html")
async def bots_endpoint(request: Request):
    return await bots(request)


@app_routes.get("/messages_log.html")
async def messages_endpoint(request: Request):
    return await messages(request)


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

        delete_interactions_by_bot_id(db=db, bot_id=bot_id)
        delete_messages_by_bot_id(db=db, bot_id=bot_id)
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
    db: Session = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
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
        raise HTTPException(status_code=400, detail="API key required")

    # Update config.yaml
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        raise HTTPException(status_code=500, detail="config.yaml not found")
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["openai_api_key"] = key
    with open(config_path, "w") as f:
        yaml.safe_dump(cfg, f)

    settings.openai_api_key = key
    return RedirectResponse(url="/settings.html", status_code=303)


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
                else "gpt-5-mini"
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


def _get_user_connector_or_404(
    db: Session, connector_id: int, current_user: User
) -> models.Connector:
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@app_routes.get("/auth/google/login")
async def google_login(request: Request):
    if not settings.google_client_id or not settings.google_client_secret:
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
