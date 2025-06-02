"""Connector for Intercom conversations."""

from typing import Any, Dict, Optional
import httpx
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class IntercomConnector(BaseConnector):
    """Send messages using the Intercom API."""

    id = "intercom"
    name = "Intercom"

    def __init__(self, access_token: str, app_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.app_id = app_id
        self.api_url = "https://api.intercom.io/messages"

    def _headers(self) -> Dict[str, str]:
        """Return HTTP headers required for API requests."""

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def send_message(self, text: str) -> Optional[str]:
        headers = self._headers()
        payload = {"message_type": "inapp", "body": text, "app_id": self.app_id}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Intercom message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Intercom messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""

        url = "https://api.intercom.io/me"
        try:
            resp = httpx.get(url, headers=self._headers())
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
