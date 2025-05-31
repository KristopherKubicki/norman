import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


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
                print(f"Error sending message to IFTTT: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """IFTTT webhooks are outbound only."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
