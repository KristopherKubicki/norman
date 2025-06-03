
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi import status
from fastapi.security import OAuth2PasswordRequestForm

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse, Response, JSONResponse
from starlette.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.schemas import Token
from app.schemas.user import UserAuthenticate, UserCreate
from app.schemas.bot import Bot, BotCreate, BotOut
from app.schemas.message import Message
from app.schemas.interaction import InteractionCreate
from app.core.config import settings
from app.core.security import create_access_token
from app.crud.user import authenticate_user
from app.crud.user import get_user_by_email, create_user
from app.crud.bot import create_bot, delete_bot, get_bot_by_id
from app.crud import connector as connector_crud
from app.crud.message import create_message, get_messages_by_bot_id, delete_message, get_last_messages_by_bot_id, delete_messages_by_bot_id
from app.crud.interaction import create_interaction
from app.handlers.openai_handler import create_chat_interaction
from app.core.exceptions import APIError
from app.core.logging import setup_logger
from app.api.deps import get_async_db

from datetime import timedelta
import os
import uuid
import requests
import jwt
from urllib.parse import urlencode
import traceback

from .views import home, connectors, filters, channels, process_message, bots, messages, captions, login, logout, get_bots
from app.connectors.connector_utils import get_connector
from app.schemas.connector import ConnectorCreate, ConnectorUpdate, Connector

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
async def home_endpoint(request: Request):
    return await home(request)

@app_routes.get("/index.html")
async def index_endpoint(request: Request):
    return await home(request)

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

@app_routes.post("/api/bots/create")
async def create_bot_endpoint(request: Request, db: Session = Depends(get_async_db)):
    form_data = await request.json()
    bot = BotCreate(**form_data)
    bot = create_bot(db=db, bot_create=bot)
    return JSONResponse(content={"id": bot.id, "name": bot.name, "description": bot.description})

@app_routes.get("/api/bots", response_model=List[BotOut])
async def get_bots_endpoint(request: Request, db: Session = Depends(get_async_db)):
    try:
        bots = await get_bots(db)
        bot_outs = [BotOut.from_orm(bot) for bot in bots]  # Convert the list of Bot objects to a list of BotOut instances
        bot_dicts = [bot_out.dict() for bot_out in bot_outs]  # Convert the list of BotOut instances to a list of dictionaries
        return JSONResponse(content=bot_dicts)  # Return the list of dictionaries as a JSONResponse
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An error occurred while fetching bots")

@app_routes.delete("/api/bots/{bot_id}")
async def delete_bot_endpoint(bot_id: int, db: Session = Depends(get_async_db)):
    delete_messages_by_bot_id(db=db, bot_id=bot_id)

    success = delete_bot(db=db, bot_id=bot_id)
    if success:
        return {"status": "success", "message": "Bot deleted successfully"}
    else:
        return {"status": "error", "message": "Failed to delete bot"}

@app_routes.get("/api/bots/{bot_id}/messages", response_model=List[Message])
async def get_messages_endpoint(
    bot_id: int,
    limit: int = 100,
    offset: int = 0,
    cursor: Optional[int] = None,
    db: Session = Depends(get_async_db),
):
    """Return messages for a bot with optional pagination."""
    try:
        cursor_int = cursor
        messages = get_messages_by_bot_id(db=db, bot_id=bot_id, limit=limit, offset=offset, cursor=cursor_int)
        return [Message.from_orm(message).dict() for message in messages]
    except Exception:
        logger.exception("Failed to fetch messages")
        raise HTTPException(status_code=500, detail="Failed to fetch messages")

@app_routes.post("/api/bots/{bot_id}/messages")
async def create_message_endpoint(
    bot_id: int,
    request: Request,
    history_limit: int = 10,
    db: Session = Depends(get_async_db),
):
    try:
        ljson = await request.json()
        user_text = ljson.get('content')
        from app.core.hooks import run_pre_hooks, run_post_hooks

        user_text, hook_ctx = await run_pre_hooks(user_text, {"bot_id": bot_id})
        message = create_message(db=db, bot_id=bot_id, text=user_text, source='user')


        # get the last messages for this bot, so it can generate a response based on history
        last_messages = get_last_messages_by_bot_id(db=db, bot_id=bot_id, limit=history_limit)

        bot = get_bot_by_id(db=db, bot_id=bot_id)

        # Create a chat interaction with OpenAI
        # Create the messages array to be sent to the OpenAI API
        messages = [
            {"role": "system", "content": bot.system_prompt}
        ]
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

        assistant_text = interaction_response['choices'][0]['message']['content']
        assistant_text, hook_ctx = await run_post_hooks(assistant_text, hook_ctx)

        # Create an interaction schema
        interaction_in = InteractionCreate(
            bot_id=bot_id,
            message_id=message.id,
            input_data=message.text,
            gpt_model=interaction_response['model'],
            output_data=assistant_text,
            tokens_in=interaction_response['usage']['prompt_tokens'],
            tokens_out=interaction_response.get("usage", {}).get("completion_tokens", 0),
            status_code=200,
            headers=str(interaction_response.get('headers', {})),
        )

        # Create a new interaction in the database
        interaction = create_interaction(db=db, interaction=interaction_in)
        message = create_message(db=db, bot_id=bot_id, text=assistant_text, source='assistant')
        return {"status": "success", "message": "Message and interaction created successfully", "data": {"message": message, "interaction": interaction}}
    except Exception as e:
        logger.exception("Failed to create message and interaction")
        return {"status": "error", "message": "Failed to create message and interaction"}


@app_routes.post("/api/connectors/create")
async def create_connector_endpoint(request: Request, db: Session = Depends(get_async_db)):
    data = await request.json()
    connector_in = ConnectorCreate(**data)
    connector = connector_crud.create(db, obj_in=connector_in)
    return JSONResponse(content=Connector.from_orm(connector).dict())


@app_routes.get("/api/connectors", response_model=List[Connector])
async def get_connectors_endpoint(db: Session = Depends(get_async_db)):
    connectors = connector_crud.get_multi(db)
    return [Connector.from_orm(c).dict() for c in connectors]


@app_routes.put("/api/connectors/{connector_id}", response_model=Connector)
async def update_connector_endpoint(connector_id: int, request: Request, db: Session = Depends(get_async_db)):
    data = await request.json()
    connector = connector_crud.get(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    updated = connector_crud.update(db, db_obj=connector, obj_in=ConnectorUpdate(**data))
    return Connector.from_orm(updated).dict()


@app_routes.delete("/api/connectors/{connector_id}")
async def delete_connector_endpoint(connector_id: int, db: Session = Depends(get_async_db)):
    connector = connector_crud.remove(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"status": "success"}


@app_routes.post("/api/connectors/{connector_id}/test")
async def test_connector_endpoint(connector_id: int, db: Session = Depends(get_async_db)):
    connector = connector_crud.get(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    instance = get_connector(connector.connector_type, connector.config or {})
    status_value = "up" if instance.is_connected() else "down"
    return {"status": status_value}


@app_routes.get("/api/connectors/{connector_id}/status")
async def connector_status_endpoint(connector_id: int, db: Session = Depends(get_async_db)):
    connector = connector_crud.get(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    instance = get_connector(connector.connector_type, connector.config or {})
    status_value = "up" if instance.is_connected() else "down"
    return {
        "status": status_value,
        "last_message_sent": connector.last_message_sent.isoformat() if connector.last_message_sent else None,
        "last_message_received": connector.last_message_received.isoformat() if connector.last_message_received else None,
        "last_successful_message": connector.last_successful_message.isoformat() if connector.last_successful_message else None,
    }

@app_routes.post("/token", response_model=Token)
async def token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_async_db)):
    user_auth = UserAuthenticate(email=form_data.username, password=form_data.password)
    user = await authenticate_user(db, user_auth)

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

@app_routes.get("/logout", response_class=HTMLResponse)
async def logout_endpoint(request: Request, response: Response):
    clear_access_token_cookie(response)
    return await logout(request)

#@app_routes.post("/login", response_class=HTMLResponse)
#async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
#    user = await authenticate_user(form_data.username, form_data.password)

@app_routes.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_async_db),
):
    """Handle username/password login and set the auth cookie."""

    user_credentials = UserAuthenticate(
        email=form_data.username, password=form_data.password
    )
    user = await authenticate_user(db, user_credentials)

    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    return _set_login_cookie(user.email)


def _random_password() -> str:
    """Generate a random password for new SSO users."""
    return uuid.uuid4().hex


def _set_login_cookie(user_email: str) -> Response:
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user_email}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


def _get_redirect_uri(request: Request, provider: str) -> str:
    return str(request.url_for(f"{provider}_callback"))


@app_routes.get("/auth/google/login")
async def google_login(request: Request):
    params = {
        "client_id": settings.google_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": _get_redirect_uri(request, "google"),
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)


@app_routes.get("/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_async_db)):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code not provided")
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
    user_info = jwt.decode(id_token, options={"verify_signature": False})
    email = user_info.get("email")
    username = user_info.get("name") or email
    if not email:
        raise HTTPException(status_code=400, detail="Email not available")
    user = get_user_by_email(db, email=email)
    if not user:
        user = create_user(db, UserCreate(email=email, username=username, password=_random_password()))
    return _set_login_cookie(user.email)


@app_routes.get("/auth/microsoft/login")
async def microsoft_login(request: Request):
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "scope": "https://graph.microsoft.com/user.read openid email profile",
        "redirect_uri": _get_redirect_uri(request, "microsoft"),
        "response_mode": "query",
    }
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urlencode(params)
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
    resp = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data=data)
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
        user = create_user(db, UserCreate(email=email, username=username, password=_random_password()))
    return _set_login_cookie(user.email)

