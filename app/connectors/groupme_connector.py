"""Connector for the GroupMe bot API."""

from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class GroupMeConnector(BaseConnector):
    """Send messages using the GroupMe bot API."""

    id = "groupme"
    name = "GroupMe"

    def __init__(self, bot_id: str, config=None) -> None:
        super().__init__(config)
        self.bot_id = bot_id
        self.api_url = "https://api.groupme.com/v3/bots/post"

    async def send_message(self, message: str) -> Optional[str]:
        payload = {"bot_id": self.bot_id, "text": message}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending GroupMe message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the GroupMe API is reachable."""
        try:
            resp = httpx.get("https://api.groupme.com/v3/bots")
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
