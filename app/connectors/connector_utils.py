# app/connectors/connector_utils.py

from .base_connector import BaseConnector
from .discord_connector import DiscordConnector
from .google_chat_connector import GoogleChatConnector
from .irc_connector import IRCConnector
from .slack_connector import SlackConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector
from .webhook_connector import WebhookConnector

connector_classes = {
        "discord": DiscordConnector,
        "google_chat": GoogleChatConnector,
        "irc": IRCConnector,
        "slack": SlackConnector,
        "teams": TeamsConnector,
        "telegram": TelegramConnector,
        "webhook": WebhookConnector
    }


def get_connector(connector_name: str):

    if connector_name not in connector_classes:
        raise ValueError(f"Invalid connector name: {connector_name}")

    connector_class = connector_classes[connector_name]
    return connector_class


def get_connectors_data():

    connectors_data = []
    for connector_class in connector_classes:
        connector = connector_classes[connector_class]
        ldata = {
            'id': connector.id,
            'name': connector.name,
            'status': 'connected',  # Replace with actual status
            'fields': [
                # Add the fields for the connector
            ],
            'last_message_sent': None,  # Replace with actual timestamp
            'enabled': True  # Replace with actual enabled status
        }
        connectors_data.append(ldata)
    return connectors_data

