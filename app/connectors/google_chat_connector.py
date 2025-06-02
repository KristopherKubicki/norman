"""Connector for Google Chat using the incoming webhook API."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector

class GoogleChatConnector(BaseConnector):

    id = 'google_chat'
    name = 'Google Chat'

    def __init__(self, service_account_key_path: str, space: str, config=None):
        super().__init__(config)
        self.service_account_key_path = service_account_key_path
        self.space = space

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Google Chat space."""
        url = f"https://chat.googleapis.com/v1/{self.space}/messages"
        headers = {"Authorization": f"Bearer {self.service_account_key_path}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json={"text": message}, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                self.logger.error("Error sending Google Chat message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Google Chat messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message

