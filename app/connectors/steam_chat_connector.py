"""Connector implementation for the Steam Chat HTTP API."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


DEFAULT_API_URL = (
    "https://api.steampowered.com/ISteamWebUserPresenceOAuth/PostMessage/v1/"
)


class SteamChatConnector(BaseConnector):
    """Connector for Steam Chat."""

    id = "steam_chat"
    name = "Steam Chat"

    def __init__(
        self, token: str, chat_id: str, api_url: Optional[str] = None, config=None
    ) -> None:
        super().__init__(config)
        self.token = token
        self.chat_id = chat_id
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Steam Chat channel."""
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"chat_id": self.chat_id, "text": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Steam Chat message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Steam Chat messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message
