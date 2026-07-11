"""Connector for sending messages via a Signal service."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class SignalConnector(BaseConnector):
    """Connector for sending and receiving Signal messages."""

    id = "signal"
    name = "Signal"

    def __init__(
        self, service_url: str, phone_number: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.service_url = service_url
        self.phone_number = phone_number

    async def send_message(self, message: str) -> Optional[str]:
        payload = {"recipient": self.phone_number, "message": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.service_url, json=payload)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Signal message: %s", exc)
                return None

    async def listen_and_process(self):
        """Listening for Signal messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Normalize incoming Signal payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}
        text = message.get("message") or message.get("text") or ""
        sender = message.get("source") or message.get("from")
        timestamp = message.get("timestamp")
        summary_parts = ["signal"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": sender,
            "timestamp": timestamp,
            "attachments": message.get("attachments"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the service URL is reachable."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(self.service_url, timeout=10)
            if resp.status_code >= 500:
                return False
            return True
        except httpx.HTTPError:
            return False
