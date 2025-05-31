import httpx
from typing import Any, Dict

from .base_connector import BaseConnector


class RestCallbackConnector(BaseConnector):
    """Connector handling REST callbacks for inbound and outbound messages."""

    id = "rest_callback"
    name = "REST Callback"

    def __init__(self, inbound_url: str, outbound_url: str, config=None):
        super().__init__(config)
        self.inbound_url = inbound_url
        self.outbound_url = outbound_url

    async def send_message(self, message: Dict[str, Any]) -> str:
        """Send an outbound callback message via HTTP POST."""
        async with httpx.AsyncClient() as client:
            response = await client.post(self.outbound_url, json=message)
            response.raise_for_status()
            return response.text

    async def listen_and_process(self):
        """Placeholder for listening for inbound callbacks."""
        pass

    async def process_incoming(self, message: Dict[str, Any]):
        """Process an inbound callback message."""
        return message
