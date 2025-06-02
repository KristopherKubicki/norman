from fastapi import Request
from fastapi.templating import Jinja2Templates
from typing import List
from fastapi import Depends
from sqlalchemy.orm import Session
import asyncio

from app.models.bot import Bot as BotModel
from app.schemas.bot import Bot
from app.api.deps import get_db, get_current_user

from app.connectors.connector_utils import get_connector, get_connectors_data

from app.core.logging import setup_logger
logger = setup_logger(__name__)



templates = Jinja2Templates(directory="app/templates")

async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "active_page": "home"},
    )

async def connectors(request: Request):
    connectors_data = get_connectors_data()
    return templates.TemplateResponse(
        request,
        "connectors.html",
        {"request": request, "connectors": connectors_data, "active_page": "connectors"},
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

async def login(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "show_navbar": False}
    )

async def logout(request: Request):
    return templates.TemplateResponse(request, "logout.html", {"request": request})

async def get_bots(db: Session, current_user=Depends(get_current_user)):
    """Return bots owned by the current authenticated user."""
    return db.query(BotModel).filter(BotModel.user_id == current_user.id).all()

async def process_message(request: Request):
    data = await request.json()
    message = data.get('message')
    channel_id = data.get('connector')

    # Use the get_connector function to get the appropriate connector for the given channel_id.
    connector = get_connector(channel_id)

    # Use the connector to process the message.
    result = connector.send_message(message)
    if asyncio.iscoroutine(result):
        response = await result
    else:
        response = result

    # Return the response to the frontend, which can be used to update the messages log.
    return templates.TemplateResponse(request, "process_message.html", {"request": request, "response": response})
