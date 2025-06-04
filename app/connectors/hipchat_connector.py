"""Connector for Atlassian HipChat rooms via the REST API."""

from typing import Any, Optional, List

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class HipChatConnector(BaseConnector):
    """Minimal implementation for HipChat."""

    id = "hipchat"
    name = "HipChat"

    def __init__(self, token: str, room_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.token = token
        self.room_id = room_id
        self.sent_messages: List[Any] = []
        self.api_url = f"https://api.hipchat.com/v2/room/{self.room_id}/notification"

    async def send_message(self, message: Any) -> Optional[str]:
        """POST ``message`` to HipChat and record it."""
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"message": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending HipChat message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for HipChat messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
