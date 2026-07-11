import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class ZapierConnector(BaseConnector):
    """Connector that posts messages to a Zapier webhook."""

    id = "zapier"
    name = "Zapier"

    def __init__(self, webhook_url: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.webhook_url = webhook_url

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.webhook_url, json=message)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                logger.error("Error sending message to Zapier: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Zapier webhooks are outbound only."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            text = str(message)
            summary = f"zapier • {text}" if text else "zapier"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["zapier"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the webhook URL appears reachable."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.head(self.webhook_url, timeout=10)
            if resp.status_code == 405:
                resp = httpx.get(self.webhook_url, timeout=10)
            return resp.status_code < 500
        except httpx.HTTPError:
            return False
