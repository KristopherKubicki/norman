"""Simple Discord connector using the HTTP API."""

import asyncio
import httpx
from typing import Any, Dict, Optional, List
from app.core.http_utils import async_get

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class DiscordConnector(BaseConnector):

    id = "discord"
    name = "Discord"

    def __init__(self, token: str, channel_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.channel_id = channel_id
        self._last_message_id: Optional[str] = None

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Discord channel."""
        url = f"https://discord.com/api/v9/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url, json={"content": message}, headers=headers
                )
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Discord message: %s", exc)
                return None

    async def _get_messages(self, after: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return recent messages from the configured Discord channel."""
        url = f"https://discord.com/api/v9/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        params = {"limit": 50}
        if after:
            params["after"] = after
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    async def listen_and_process(self) -> None:
        """Poll for new Discord messages and process them."""
        while True:
            try:
                messages = await self._get_messages(after=self._last_message_id)
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error fetching Discord messages: %s", exc)
                await asyncio.sleep(5)
                continue

            for msg in reversed(messages):
                self._last_message_id = msg.get("id", self._last_message_id)
                result = self.process_incoming(msg)
                if asyncio.iscoroutine(result):
                    await result

            await asyncio.sleep(5)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Extract basic fields from a Discord message payload."""
        return {
            "id": message.get("id"),
            "text": message.get("content", ""),
            "user": message.get("author", {}).get("username"),
            "channel": message.get("channel_id", self.channel_id),
        }

    async def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""
        url = "https://discord.com/api/v9/users/@me"
        headers = {"Authorization": f"Bot {self.token}"}
        try:
            await async_get(url, headers=headers)
            return True
        except httpx.HTTPError:
            return False
