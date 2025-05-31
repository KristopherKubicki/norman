"""Connector for publishing messages using OPC UA PubSub."""

from typing import Any, Optional

from .base_connector import BaseConnector


class OPCUAPubSubConnector(BaseConnector):
    """Placeholder connector for OPC UA PubSub."""

    id = "opcua_pubsub"
    name = "OPC UA PubSub"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: list[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for OPC UA messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound OPC UA messages
        return message
