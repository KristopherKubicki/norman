"""Connector for the Viber Bots API."""

from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class ViberConnector(BaseConnector):
    """Send messages to Viber using the Bots API."""

    id = "viber"
    name = "Viber Bots"

    def __init__(
        self, auth_token: str, receiver: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.auth_token = auth_token
        self.receiver = receiver
        self.api_url = "https://chatapi.viber.com/pa/send_message"

    async def send_message(self, text: str) -> Optional[str]:
        headers = {"X-Viber-Auth-Token": self.auth_token}
        payload = {"receiver": self.receiver, "type": "text", "text": text}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Viber message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Viber messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"text": str(message)}
        msg = message.get("message") or {}
        text = msg.get("text") or ""
        sender = (message.get("sender") or {}).get("id")
        timestamp = message.get("timestamp")
        summary_parts = ["viber"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": sender,
            "timestamp": timestamp,
            "type": msg.get("type"),
            "tracking_data": message.get("tracking_data"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the auth token is valid."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                "https://chatapi.viber.com/pa/get_account_info",
                headers={"X-Viber-Auth-Token": self.auth_token},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
