"""Simple Discord connector using the HTTP API."""

import asyncio
import importlib
from typing import Any, Dict, Optional, List

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class DiscordConnector(BaseConnector):
    id = "discord"
    name = "Discord"

    def __init__(
        self,
        token: Optional[str],
        channel_id: Optional[str],
        webhook_url: Optional[str] = None,
        config=None,
    ):
        super().__init__(config)
        self.token = token
        self.channel_id = channel_id
        self.webhook_url = webhook_url
        self._last_message_id: Optional[str] = None

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Discord channel."""
        if self.webhook_url:
            url = self.webhook_url
            headers = {}
            payload = {"content": message}
        else:
            if not self.token or not self.channel_id:
                return None
            url = f"https://discord.com/api/v9/channels/{self.channel_id}/messages"
            headers = {"Authorization": f"Bot {self.token}"}
            payload = {"content": message}
        httpx = importlib.import_module("httpx")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Discord message: %s", exc)
                return None

    async def _get_messages(self, after: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return recent messages from the configured Discord channel."""
        if not self.token or not self.channel_id:
            return []
        url = f"https://discord.com/api/v9/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        params = {"limit": 50}
        httpx = importlib.import_module("httpx")
        if after:
            params["after"] = after
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    async def listen_and_process(self) -> None:
        """Poll for new Discord messages and process them."""
        if not self.token or not self.channel_id:
            return None
        httpx = importlib.import_module("httpx")
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
        """Extract basic fields from a Discord message or webhook payload."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        author = message.get("author") or {}
        text = message.get("content") or message.get("text") or ""
        channel = message.get("channel_id") or message.get("channel") or self.channel_id
        user = author.get("username") or author.get("id")
        msg_id = message.get("id")

        summary_parts = ["discord"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "id": msg_id,
            "text": text,
            "user": user,
            "channel": channel,
            "timestamp": message.get("timestamp"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""
        if self.webhook_url:
            url = self.webhook_url
            headers = {}
        else:
            if not self.token:
                return False
            url = "https://discord.com/api/v9/users/@me"
            headers = {"Authorization": f"Bot {self.token}"}
        httpx = importlib.import_module("httpx")
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
