import httpx
from typing import Optional, List, Any

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class DingTalkConnector(BaseConnector):
    """Connector for Alibaba DingTalk chat messages."""

    id = "dingtalk"
    name = "DingTalk"

    def __init__(self, access_token: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.sent_messages = []
        self.api_url = f"https://oapi.dingtalk.com/robot/send?access_token={self.access_token}"

    async def send_message(self, message) -> Optional[str]:
        """POST ``message`` to DingTalk and record it."""
        payload = {"msgtype": "text", "text": {"content": message}}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending DingTalk message: %s", exc)
                return None

    async def listen_and_process(self):
        """Listening for DingTalk messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
