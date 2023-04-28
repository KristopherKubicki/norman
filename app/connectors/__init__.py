
from fastapi import FastAPI
from app.core.config import Settings

#from .base_connector import BaseConnector
from .irc_connector import IRCConnector
from .slack_connector import SlackConnector
from .google_chat_connector import GoogleChatConnector
from .discord_connector import DiscordConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector
from .webhook_connector import WebhookConnector


def init_connectors(app: FastAPI, settings: Settings):
    app.state.telegram_connector = TelegramConnector(token=settings.telegram_token, chat_id=settings.telegram_chat_id)
    app.state.slack_connector = SlackConnector(token=settings.slack_token, channel_id=settings.slack_channel_id)
    app.state.google_chat_connector = GoogleChatConnector(service_account_key_path=settings.google_chat_service_account_key_path, space=settings.google_chat_space)
    app.state.discord_connector = DiscordConnector(token=settings.discord_token, channel_id=settings.discord_channel_id)
    app.state.teams_connector = TeamsConnector(app_id=settings.teams_app_id, app_password=settings.teams_app_password, tenant_id=settings.teams_tenant_id, bot_endpoint=settings.teams_bot_endpoint)
