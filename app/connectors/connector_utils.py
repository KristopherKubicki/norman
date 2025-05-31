# app/connectors/connector_utils.py

"""Utility helpers for working with connector classes.

This module centralizes the available connector implementations and provides
helpers for instantiating them from the application configuration.  The
previous version of :func:`get_connectors_data` returned static placeholder
information.  It now inspects the connector constructors and configuration to
return real metadata about each connector.
"""

import inspect
from typing import Any, Dict, List

from app.core.config import get_settings

from .base_connector import BaseConnector
from .discord_connector import DiscordConnector
from .google_chat_connector import GoogleChatConnector
from .irc_connector import IRCConnector
from .slack_connector import SlackConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector
from .twitch_connector import TwitchConnector
from .webhook_connector import WebhookConnector
from .whatsapp_connector import WhatsAppConnector
from .matrix_connector import MatrixConnector

# Registry of available connectors keyed by their identifier.
connector_classes: Dict[str, type] = {
    "discord": DiscordConnector,
    "google_chat": GoogleChatConnector,
    "irc": IRCConnector,
    "slack": SlackConnector,
    "teams": TeamsConnector,
    "telegram": TelegramConnector,
    "twitch": TwitchConnector,
    "webhook": WebhookConnector,
    "whatsapp": WhatsAppConnector,
    "matrix": MatrixConnector,
}


def get_connector(connector_name: str) -> BaseConnector:
    """Return an instantiated connector configured from settings."""

    if connector_name not in connector_classes:
        raise ValueError(f"Invalid connector name: {connector_name}")

    connector_class = connector_classes[connector_name]

    settings = get_settings()
    signature = inspect.signature(connector_class.__init__)
    kwargs: Dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.name == "self":
            continue
        setting_name = f"{connector_name}_{param.name}"
        kwargs[param.name] = getattr(settings, setting_name, None)

    return connector_class(**kwargs)


def get_connectors_data() -> List[Dict[str, Any]]:
    """Return metadata about all available connectors.

    The configuration values are inspected to determine whether each connector
    is enabled.  No network calls are made, so the ``status`` field simply
    reflects whether the connector has been configured.
    """

    settings = get_settings()
    connectors_data: List[Dict[str, Any]] = []

    for name, connector_cls in connector_classes.items():
        signature = inspect.signature(connector_cls.__init__)
        fields = [p.name for p in signature.parameters.values() if p.name != "self"]

        configured = True
        for field in fields:
            setting_name = f"{name}_{field}"
            value = getattr(settings, setting_name, None)
            if value in (None, "", f"your_{setting_name}"):
                configured = False
        connectors_data.append(
            {
                "id": connector_cls.id,
                "name": connector_cls.name,
                "status": "configured" if configured else "missing_config",
                "fields": fields,
                "last_message_sent": None,
                "enabled": configured,
            }
        )

    return connectors_data

