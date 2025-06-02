"""Connector for sending messages to Zoom chat via REST API."""

import importlib
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class ZoomConnector(BaseConnector):
    """Simplified connector for Zoom chat."""

    id = "zoom"
    name = "Zoom"

    def __init__(self, token: str, to_jid: str, account_id: str = "me", config=None):
        super().__init__(config)
        self.token = token
        self.to_jid = to_jid
        self.account_id = account_id

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Zoom chat recipient."""
        url = f"https://api.zoom.us/v2/chat/users/{self.account_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"message": message, "to_jid": self.to_jid}
        httpx = importlib.import_module("httpx")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Zoom message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Zoom messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return a simplified representation of a Zoom chat message."""
        return {
            "text": message.get("message", ""),
            "user": message.get("sender"),
            "channel": message.get("to_jid", self.to_jid),
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the access token appears valid."""
        url = "https://api.zoom.us/v2/users/me"
        headers = {"Authorization": f"Bearer {self.token}"}
        httpx = importlib.import_module("httpx")
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
