"""Simple Facebook Messenger connector using the Graph API."""

import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class FacebookMessengerConnector(BaseConnector):
    """Connector for Facebook Messenger."""

    id = "facebook_messenger"
    name = "Facebook Messenger"

    def __init__(
        self, page_token: str, verify_token: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.page_token = page_token
        self.verify_token = verify_token
        self.api_url = "https://graph.facebook.com/v17.0/me/messages"

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Send ``message`` payload using the Graph API."""
        params = {"access_token": self.page_token}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, params=params, json=message)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Facebook message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Return immediately as Messenger does not offer a polling API."""

        self.logger.info(
            "Facebook Messenger connector does not support incoming messages"
        )
        await asyncio.sleep(0)

    async def process_incoming(self, message):
        """Normalize incoming Messenger webhook payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        entry = (message.get("entry") or [{}])[0]
        messaging = entry.get("messaging") or entry.get("messages") or []
        event = messaging[0] if messaging else {}
        msg = event.get("message") or {}
        text = msg.get("text") or ""
        sender = (event.get("sender") or {}).get("id")
        recipient = (event.get("recipient") or {}).get("id")
        timestamp = event.get("timestamp")
        attachments = msg.get("attachments") or []

        summary_parts = ["facebook"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "sender": sender,
            "recipient": recipient,
            "timestamp": timestamp,
            "attachments": attachments,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the page token is valid."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                "https://graph.facebook.com/v17.0/me",
                params={"access_token": self.page_token},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
