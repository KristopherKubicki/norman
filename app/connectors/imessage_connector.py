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

    def __init__(
        self, service_url: str, phone_number: str, config: Optional[dict] = None
    ) -> None:
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
        if not isinstance(message, dict):
            text = str(message)
            summary = f"imessage • {text}" if text else "imessage"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["imessage"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": message.get("from") or message.get("sender"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the connector is configured."""
        return super().is_connected()
