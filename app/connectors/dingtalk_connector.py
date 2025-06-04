from typing import Optional

import httpx

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
        self.base_url = (
            f"https://oapi.dingtalk.com/robot/send?access_token={self.access_token}"
        )

    async def send_message(self, message: str) -> str:
        """Send ``message`` via the DingTalk robot API."""
        payload = {"msgtype": "text", "text": {"content": message}}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.base_url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending DingTalk message: %s", exc)
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for DingTalk messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the access token appears valid."""

        url = f"https://oapi.dingtalk.com/robot/get?access_token={self.access_token}"
        try:
            resp = httpx.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("errcode", 1) == 0
        except httpx.HTTPError:
            return False
