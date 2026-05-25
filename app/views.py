import asyncio
import re
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session


from app.connectors.connector_utils import get_connector, get_connectors_data
from app.core.config import settings
from app.core.security import decode_access_token
from app.crud.user import get_user_by_email
from app import models

from app.core.logging import setup_logger

logger = setup_logger(__name__)


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["settings"] = settings


def _load_app_version() -> str:
    try:
        return package_version("norman")
    except PackageNotFoundError:
        pass

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        content = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"

    in_project = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        match = re.match(r'version\s*=\s*"([^"]+)"', stripped)
        if match:
            return match.group(1)
    return "0.0.0"


templates.env.globals["app_version"] = _load_app_version()
_SWITCHBOARD_HOSTS = {"switchboard.home.arpa", "switchboard.norman.home.arpa"}


def _sso_enabled(client_id: str, client_secret: str) -> bool:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        return False
    # config.yaml.dist placeholders look like "your_google_client_id".
    if client_id.startswith("your_") or client_secret.startswith("your_"):
        return False
    return True


def _switchboard_mode(request: Request) -> bool:
    view = str(request.query_params.get("view") or "").strip().lower()
    request_host = (request.headers.get("host") or "").split(":", 1)[0].strip().lower()
    return view in {"switchboard", "bbs"} or request_host in _SWITCHBOARD_HOSTS


async def home(request: Request, db: Optional[Session] = None):
    embed_mode = str(request.query_params.get("embed") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dashboard_view = str(request.query_params.get("view") or "").strip().lower()
    switchboard_mode = dashboard_view == "switchboard" or _switchboard_mode(request)
    token = request.cookies.get("access_token")
    user_email = decode_access_token(token) if token else None
    bot_count = 0
    connector_count = 0
    channel_count = 0
    filter_count = 0
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
            channel_count = (
                db.query(models.Channel)
                .join(
                    models.Connector, models.Channel.connector_id == models.Connector.id
                )
                .filter(models.Connector.user_id == user.id)
                .count()
            )
            filter_count = (
                db.query(models.Filter)
                .join(models.Channel, models.Filter.channel_id == models.Channel.id)
                .join(
                    models.Connector, models.Channel.connector_id == models.Connector.id
                )
                .filter(models.Connector.user_id == user.id)
                .count()
            )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "active_page": "home",
            "embed_mode": embed_mode,
            "dashboard_view": dashboard_view,
            "switchboard_mode": switchboard_mode,
            "show_navbar": not embed_mode,
            "show_statusbar": not embed_mode,
            "user_email": user_email,
            "openai_configured": bool(settings.openai_api_key),
            "bot_count": bot_count,
            "connector_count": connector_count,
            "channel_count": channel_count,
            "filter_count": filter_count,
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


async def actions(request: Request):
    return templates.TemplateResponse(
        request,
        "actions.html",
        {"request": request, "active_page": "actions"},
    )


async def channels(request: Request):
    switchboard_mode = _switchboard_mode(request)
    return templates.TemplateResponse(
        request,
        "channels.html",
        {
            "request": request,
            "active_page": "channels",
            "switchboard_mode": switchboard_mode,
            "bbs_mode": switchboard_mode,
        },
    )


async def messages(request: Request):
    shell_mode = str(request.query_params.get("shell") or "").strip().lower()
    super_tui_mode = shell_mode == "prime"
    switchboard_mode = _switchboard_mode(request) and not super_tui_mode
    return templates.TemplateResponse(
        request,
        "messages_log.html",
        {
            "request": request,
            "active_page": "messages",
            "shell_mode": shell_mode,
            "super_tui_mode": super_tui_mode,
            "switchboard_mode": switchboard_mode,
            "bbs_mode": switchboard_mode,
            "dashboard_embed_url": "/dashboard.html?embed=1",
        },
    )


async def consoles(request: Request):
    advanced = str(request.query_params.get("advanced", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not advanced:
        return RedirectResponse(
            url="/messages_log.html?pane=consoles",
            status_code=307,
        )
    return templates.TemplateResponse(
        request,
        "consoles.html",
        {"request": request, "active_page": "consoles"},
    )


async def bots(request: Request):
    return templates.TemplateResponse(
        request,
        "bots.html",
        {"request": request, "active_page": "bots"},
    )


async def systems(request: Request):
    return templates.TemplateResponse(
        request,
        "systems.html",
        {"request": request, "active_page": "systems"},
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
        request,
        "login.html",
        {
            "request": request,
            "active_page": "login",
            "show_navbar": False,
            "show_statusbar": False,
            "google_sso_enabled": _sso_enabled(
                settings.google_client_id, settings.google_client_secret
            ),
            "microsoft_sso_enabled": _sso_enabled(
                settings.microsoft_client_id, settings.microsoft_client_secret
            ),
        },
    )


async def setup(request: Request):
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "request": request,
            "active_page": "setup",
            "show_navbar": False,
            "show_statusbar": False,
        },
    )


async def settings_page(request: Request, openai_configured: bool):
    status = request.query_params.get("status")
    message = request.query_params.get("message")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "openai_configured": openai_configured,
            "settings_status": status,
            "settings_message": message,
            "google_sso_enabled": _sso_enabled(
                settings.google_client_id, settings.google_client_secret
            ),
            "microsoft_sso_enabled": _sso_enabled(
                settings.microsoft_client_id, settings.microsoft_client_secret
            ),
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
