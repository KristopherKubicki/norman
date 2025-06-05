"""Connector for the Kik messaging platform using the HTTP API."""

from typing import Any, Dict, Optional

import asyncio
import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class KikConnector(BaseConnector):
    """Connector for interacting with Kik's bot API."""

    id = "kik"
    name = "Kik"

    def __init__(
        self, username: str, api_key: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.username = username
        self.api_key = api_key
        self.api_url = "https://api.kik.com/v1"

    async def send_message(
        self, message: str, to: Optional[str] = None
    ) -> Optional[str]:
        """Send ``message`` to ``to`` using Kik's HTTP API."""

        payload = {
            "messages": [
                {
                    "type": "text",
                    "to": to or self.username,
                    "body": message,
                }
            ]
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/message",
                    json=payload,
                    auth=(self.username, self.api_key),
                )
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Kik message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Kik bots primarily use webhooks; no polling implementation."""

        self.logger.info("Kik connector does not support polling for messages")
        await asyncio.sleep(0)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize an incoming Kik message payload."""

        return {
            "text": message.get("body", ""),
            "from": message.get("from"),
            "id": message.get("id"),
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the API credentials appear valid."""

        try:
            resp = httpx.get(
                f"{self.api_url}/config", auth=(self.username, self.api_key)
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
