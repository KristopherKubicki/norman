"""Connector for interacting with the Pinterest API."""

import importlib
from typing import Any, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)

class PinterestConnector(BaseConnector):
    """Connector for creating pins on a Pinterest board."""

    id = "pinterest"
    name = "Pinterest"

    def __init__(self, access_token: str, board_id: str, config=None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.board_id = board_id
        self.api_url = "https://api.pinterest.com/v5/pins"
        self.sent_messages = []

    async def send_message(self, message: str) -> Optional[str]:
        """Create a pin with ``message`` as the note on ``board_id``."""
        httpx = importlib.import_module("httpx")
        payload = {"board_id": self.board_id, "note": message}
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Pinterest message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""
        httpx = importlib.import_module("httpx")
        url = "https://api.pinterest.com/v5/user_account"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
