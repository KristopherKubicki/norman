import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class RESTCallbackConnector(BaseConnector):
    """Connector that forwards messages to a REST endpoint."""

    id = "rest_callback"
    name = "REST Callback"

    def __init__(self, callback_url: str, config=None) -> None:
        super().__init__(config)
        self.callback_url = callback_url

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Send a message to the configured callback URL."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.callback_url, json=message)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                print(f"Error sending message to {self.callback_url}: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """This connector does not support incoming messages."""
        raise NotImplementedError(
            "RESTCallbackConnector cannot listen for incoming messages"
        )

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Forward an incoming message to the callback URL."""
        await self.send_message(message)
        return message
