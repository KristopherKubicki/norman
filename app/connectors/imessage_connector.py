"""Connector for sending Apple iMessage/Business Chat messages."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class IMessageConnector(BaseConnector):
    """Connector for Apple RCS/iMessage."""

    id = "imessage"
    name = "Apple RCS/iMessage"

    def __init__(self, service_url: str, phone_number: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.service_url = service_url
        self.phone_number = phone_number

    async def send_message(self, message: str) -> Optional[str]:
        """POST ``message`` to the configured service URL."""
        payload = {"to": self.phone_number, "message": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.service_url, json=payload)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending iMessage: %s", exc)
                return None

    async def listen_and_process(self):
        """Listening for iMessage messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
