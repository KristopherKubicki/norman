"""Connector for sending messages over CoAP secured with OSCORE."""

from typing import Any, Optional

from .base_connector import BaseConnector


class CoAPOSCOREConnector(BaseConnector):
    """Minimal placeholder connector for CoAP + OSCORE."""

    id = "coap_oscore"
    name = "CoAP + OSCORE"

    def __init__(self, host: str, port: int = 5684, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port

    async def send_message(self, message: Any) -> None:
        # Placeholder for sending a CoAP message with OSCORE protection
        pass

    async def listen_and_process(self) -> None:
        # Placeholder for listening for CoAP messages
        pass

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound CoAP messages
        return message
