"""Connector for Apple Messages for Business."""

from typing import Any, Dict, Optional
import httpx
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class AppleMessagesBusinessConnector(BaseConnector):
    """Send messages via Apple Messages for Business."""

    id = "apple_messages_business"
    name = "Apple Messages for Business"

    def __init__(
        self, access_token: str, sender_id: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.sender_id = sender_id
        self.api_url = "https://api.apple.com/business/v1/messages"

    async def send_message(self, text: str) -> Optional[str]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"sender": {"id": self.sender_id}, "message": {"text": text}}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Apple Messages for Business: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Apple Messages for Business is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"text": str(message)}
        text = message.get("message", {}).get("text") or message.get("text") or ""
        sender = (message.get("sender") or {}).get("id")
        summary_parts = ["apple_messages"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": sender,
            "message_id": message.get("messageId") or message.get("id"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the access token is present."""
        return super().is_connected()
