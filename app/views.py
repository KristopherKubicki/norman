from fastapi import Request
from sqlalchemy.orm import Session
from typing import Optional
from fastapi.templating import Jinja2Templates
import asyncio


from app.connectors.connector_utils import get_connector, get_connectors_data
from app.core.config import settings
from app.core.security import decode_access_token
from app.crud.user import get_user_by_email
from app import models

from app.core.logging import setup_logger

logger = setup_logger(__name__)


templates = Jinja2Templates(directory="app/templates")


async def home(request: Request, db: Optional[Session] = None):
    token = request.cookies.get("access_token")
    user_email = decode_access_token(token) if token else None
    bot_count = 0
    connector_count = 0
    if db and user_email:
        user = get_user_by_email(db, email=user_email)
        if user:
            bot_count = (
                db.query(models.Bot).filter(models.Bot.user_id == user.id).count()
            )
            connector_count = (
                db.query(models.Connector)
                .filter(models.Connector.user_id == user.id)
                .count()
            )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "active_page": "home",
            "user_email": user_email,
            "openai_configured": bool(settings.openai_api_key),
            "bot_count": bot_count,
            "connector_count": connector_count,
            "onboarding_ready": bot_count > 0 and connector_count > 0,
        },
    )


async def connectors(request: Request):
    connectors_data = get_connectors_data()
    return templates.TemplateResponse(
        request,
        "connectors.html",
        {
            "request": request,
            "connectors": connectors_data,
            "active_page": "connectors",
        },
    )


async def filters(request: Request):
    return templates.TemplateResponse(
        request,
        "filters.html",
        {"request": request, "active_page": "filters"},
    )


async def channels(request: Request):
    return templates.TemplateResponse(
        request,
        "channels.html",
        {"request": request, "active_page": "channels"},
    )


async def messages(request: Request):
    return templates.TemplateResponse(
        request,
        "messages_log.html",
        {"request": request, "active_page": "messages"},
    )


async def bots(request: Request):
    return templates.TemplateResponse(
        request,
        "bots.html",
        {"request": request, "active_page": "bots"},
    )


async def captions(request: Request):
    return templates.TemplateResponse(
        request,
        "captions.html",
        {"request": request, "active_page": "captions"},
    )


async def quickstart(request: Request):
    return templates.TemplateResponse(
        request,
        "quickstart.html",
        {"request": request, "active_page": "quickstart"},
    )


async def login(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"request": request, "show_navbar": False}
    )


async def setup(request: Request):
    return templates.TemplateResponse(
        request, "setup.html", {"request": request, "show_navbar": False}
    )


async def settings_page(request: Request, openai_configured: bool):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "openai_configured": openai_configured,
        },
    )


async def logout(request: Request):
    return templates.TemplateResponse(request, "logout.html", {"request": request})


async def process_message(request: Request):
    data = await request.json()
    message = data.get("message")
    channel_id = data.get("connector")

    # Use the get_connector function to get the appropriate connector for the given channel_id.
    connector = get_connector(channel_id)

    # Use the connector to process the message.
    result = connector.send_message(message)
    if asyncio.iscoroutine(result):
        response = await result
    else:
        response = result

    # Return the response to the frontend, which can be used to update the messages log.
    return templates.TemplateResponse(
        request, "process_message.html", {"request": request, "response": response}
    )
