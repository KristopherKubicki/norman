# app/connectors/__init__.py

from fastapi import FastAPI
from app.core.config import Settings

#from .base_connector import BaseConnector
from .irc_connector import IRCConnector
from . import irc_connector as irc
from .slack_connector import SlackConnector
from .google_chat_connector import GoogleChatConnector
from .discord_connector import DiscordConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector
from .webhook_connector import WebhookConnector
from .rest_callback_connector import RESTCallbackConnector
from .whatsapp_connector import WhatsAppConnector
from .matrix_connector import MatrixConnector
from .signal_connector import SignalConnector
from .twitch_connector import TwitchConnector
from .mcp_connector import MCPConnector

from .connector_utils import get_connector

def init_connectors(app: FastAPI, settings: Settings):
    app.state.telegram_connector = TelegramConnector(token=settings.telegram_token, chat_id=settings.telegram_chat_id)
    app.state.slack_connector = SlackConnector(token=settings.slack_token, channel_id=settings.slack_channel_id)
    app.state.google_chat_connector = GoogleChatConnector(service_account_key_path=settings.google_chat_service_account_key_path, space=settings.google_chat_space)
    app.state.discord_connector = DiscordConnector(token=settings.discord_token, channel_id=settings.discord_channel_id)
    app.state.teams_connector = TeamsConnector(app_id=settings.teams_app_id, app_password=settings.teams_app_password, tenant_id=settings.teams_tenant_id, bot_endpoint=settings.teams_bot_endpoint)
    app.state.whatsapp_connector = WhatsAppConnector(
        account_sid=settings.whatsapp_account_sid,
        auth_token=settings.whatsapp_auth_token,
        from_number=settings.whatsapp_from_number,
        to_number=settings.whatsapp_to_number,
    )
    app.state.signal_connector = SignalConnector(
        service_url=settings.signal_service_url,
        phone_number=settings.signal_phone_number,
    )
    app.state.matrix_connector = MatrixConnector(
        homeserver=settings.matrix_homeserver,
        user_id=settings.matrix_user_id,
        access_token=settings.matrix_access_token,
        room_id=settings.matrix_room_id,
    )
    app.state.twitch_connector = TwitchConnector(
        token=settings.twitch_token,
        nickname=settings.twitch_nickname,
        channel=settings.twitch_channel,
        server=settings.twitch_server,
        port=settings.twitch_port,
    )
    app.state.rest_callback_connector = RESTCallbackConnector(
        callback_url=settings.rest_callback_url
    )
    app.state.mcp_connector = MCPConnector(
        api_url=settings.mcp_api_url,
        api_key=settings.mcp_api_key,
    )
