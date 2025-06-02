"""Simple Facebook Messenger connector using the Graph API."""

import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class FacebookMessengerConnector(BaseConnector):
    """Connector for Facebook Messenger."""

    id = "facebook_messenger"
    name = "Facebook Messenger"

    def __init__(self, page_token: str, verify_token: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.page_token = page_token
        self.verify_token = verify_token
        self.api_url = "https://graph.facebook.com/v17.0/me/messages"

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Send ``message`` payload using the Graph API."""
        params = {"access_token": self.page_token}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, params=params, json=message)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error sending Facebook message: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """Return immediately as Messenger does not offer a polling API."""

        self.logger.info("Facebook Messenger connector does not support incoming messages")
        await asyncio.sleep(0)

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
