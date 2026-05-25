"""Connector for Google Business Messages / RCS."""

from typing import Any, Dict, Optional
import httpx
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class GoogleBusinessRCSConnector(BaseConnector):
    """Send messages using Google Business Messages (RCS)."""

    id = "google_business_rcs"
    name = "Google Business Messages / RCS"

    def __init__(
        self, access_token: str, phone_number: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.phone_number = phone_number
        self.api_url = "https://businessmessages.googleapis.com/v1"

    async def send_message(self, text: str) -> Optional[str]:
        url = f"{self.api_url}/conversations/{self.phone_number}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"message": {"text": text}}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Google Business message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Google Business Messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            text = str(message)
            summary = f"gbm • {text}" if text else "gbm"
            return {"text": text, "text_summary": summary}
        text = (
            message.get("message", {}).get("text")
            if isinstance(message.get("message"), dict)
            else message.get("text")
        ) or ""
        summary_parts = ["gbm"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": message.get("sender") or message.get("senderId"),
            "conversation_id": message.get("conversationId"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the access token works."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"{self.api_url}/conversations/{self.phone_number}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
