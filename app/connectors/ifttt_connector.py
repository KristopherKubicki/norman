import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class IFTTTConnector(BaseConnector):
    """Connector that posts messages to an IFTTT webhook."""

    id = "ifttt"
    name = "IFTTT"

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
                logger.error("Error sending message to IFTTT: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """IFTTT webhooks are outbound only."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
