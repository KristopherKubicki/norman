import httpx
from typing import Optional, List, Any

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class TwitterConnector(BaseConnector):
    """Connector for X.com (Twitter) direct messages."""

    id = "twitter"
    name = "X.com (Twitter)"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
        config=None,
    ):
        super().__init__(config)
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.sent_messages: List[Any] = []
        self.api_url = "https://api.twitter.com/2/direct_messages"

    async def send_message(self, message) -> Optional[str]:
        """POST ``message`` to the X.com API and record it."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"text": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Twitter message: %s", exc)
                return None

    async def listen_and_process(self):
        """Listening to X.com/Twitter messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
