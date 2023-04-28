from typing import List
from fastapi import FastAPI
from .base_connector import BaseConnector
from .irc_connector import IRCConnector
from .slack_connector import SlackConnector
from .google_chat_connector import GoogleChatConnector
from .discord_connector import DiscordConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector

CONNECTOR_CLASSES = {
    "irc": IRCConnector,
    "slack": SlackConnector,
    "google_chat": GoogleChatConnector,
    "discord": DiscordConnector,
    "teams": TeamsConnector,
    "telegram": TelegramConnector,
}

def init_connectors(app: FastAPI, connectors_config: List[dict]):
    for connector_config in connectors_config:
        connector_type = connector_config["type"]
        ConnectorClass = CONNECTOR_CLASSES.get(connector_type)

        if ConnectorClass:
            connector_instance = ConnectorClass(connector_config)
            connector_instance.register_routes(app)

            if hasattr(connector_instance, "initialize"):
                connector_instance.initialize()
        else:
            print(f"Unknown connector type '{connector_type}', skipping.")

