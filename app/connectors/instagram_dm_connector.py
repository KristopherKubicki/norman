"""Connector for sending Instagram direct messages via the Graph API."""

import asyncio
from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class InstagramDMConnector(BaseConnector):
    """Connector for Instagram direct messages."""

    id = "instagram_dm"
    name = "Instagram DM"

    def __init__(
        self, access_token: str, user_id: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.user_id = user_id
        self.api_url = f"https://graph.facebook.com/v17.0/{self.user_id}/messages"
        self.sent_messages: list = []

    async def send_message(self, message: str) -> str:
        """Send ``message`` via the Graph API and record it locally."""
        payload: Dict[str, Any] = {
            "recipient": {"id": self.user_id},
            "message": {"text": message},
        }
        params = {"access_token": self.access_token}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, params=params, json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Instagram DM: %s", exc)

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Instagram DM polling is not implemented."""
        logger.info("Instagram DM connector does not support incoming messages")
        await asyncio.sleep(0)

    async def process_incoming(self, message: Any) -> Any:
        """Normalize Instagram webhook payloads."""
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

        summary_parts = ["instagram"]
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
        """Return ``True`` if the access token is valid."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"https://graph.facebook.com/v17.0/{self.user_id}",
                params={"access_token": self.access_token},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
