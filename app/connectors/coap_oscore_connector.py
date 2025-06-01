"""Connector for sending messages over CoAP secured with OSCORE."""

from typing import Any, List, Optional

from .base_connector import BaseConnector


class CoAPOSCOREConnector(BaseConnector):
    """Minimal placeholder connector for CoAP + OSCORE."""

    id = "coap_oscore"
    name = "CoAP + OSCORE"

    def __init__(self, host: str, port: int = 5684, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for CoAP messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound CoAP messages
        return message
