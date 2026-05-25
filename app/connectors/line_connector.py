"""Connector for the LINE Messaging API."""

from typing import Any, Dict, Optional

import asyncio

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class LineConnector(BaseConnector):
    """Send messages to LINE users via the Messaging API."""

    id = "line"
    name = "LINE Messaging"

    def __init__(
        self, channel_access_token: str, user_id: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.channel_access_token = channel_access_token
        self.user_id = user_id
        self.api_url = "https://api.line.me/v2/bot/message/push"

    async def send_message(self, text: str) -> Optional[str]:
        headers = {"Authorization": f"Bearer {self.channel_access_token}"}
        payload = {"to": self.user_id, "messages": [{"type": "text", "text": text}]}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending LINE message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Return immediately as LINE does not support polling for messages."""

        self.logger.info("LINE connector does not support incoming messages")
        await asyncio.sleep(0)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"text": str(message)}
        events = message.get("events") or []
        event = events[0] if events else {}
        msg = event.get("message") or {}
        text = msg.get("text") or ""
        summary_parts = ["line"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "reply_token": event.get("replyToken"),
            "user_id": (event.get("source") or {}).get("userId"),
            "event_type": event.get("type"),
            "timestamp": event.get("timestamp"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the connector is configured."""
        return super().is_connected()
