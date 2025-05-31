"""Rocket.Chat connector using the HTTP REST API."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class RocketChatConnector(BaseConnector):
    """Connector for interacting with a Rocket.Chat server."""

    id = "rocketchat"
    name = "Rocket.Chat"

    def __init__(self, url: str, token: str, user_id: str, config=None) -> None:
        super().__init__(config)
        self.url = url.rstrip('/')
        self.token = token
        self.user_id = user_id

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the Rocket.Chat server."""
        api_url = f"{self.url}/api/v1/chat.postMessage"
        headers = {"X-Auth-Token": self.token, "X-User-Id": self.user_id}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(api_url, json={"text": message}, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error sending Rocket.Chat message: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """Listening for Rocket.Chat messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message
