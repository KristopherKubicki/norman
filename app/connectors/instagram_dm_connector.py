import httpx
from typing import Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class InstagramDMConnector(BaseConnector):
    """Connector for Instagram direct messages."""

    id = "instagram_dm"
    name = "Instagram DM"

    def __init__(self, access_token: str, user_id: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.user_id = user_id
        self.api_url = f"https://graph.facebook.com/v17.0/{self.user_id}/messages"
        self.sent_messages = []

    async def send_message(self, text: str) -> Optional[str]:
        """Send ``text`` via the Instagram Graph API."""

        data = {
            "recipient": {"id": self.user_id},
            "messaging_type": "UPDATE",
            "message": {"text": text},
        }
        params = {"access_token": self.access_token}
        self.sent_messages.append(text)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, params=params, json=data)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Instagram DM: %s", exc)
            return None

    async def listen_and_process(self):
        """Listening for Instagram DM messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the access token appears valid."""

        url = "https://graph.facebook.com/v17.0/me"
        try:
            resp = httpx.get(url, params={"access_token": self.access_token})
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
