"""Connector for Intercom conversations."""

from typing import Any, Dict, Optional
import httpx
from .base_connector import BaseConnector


class IntercomConnector(BaseConnector):
    """Send messages using the Intercom API."""

    id = "intercom"
    name = "Intercom"

    def __init__(self, access_token: str, app_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.app_id = app_id
        self.api_url = "https://api.intercom.io/messages"

    async def send_message(self, text: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {"message_type": "inapp", "body": text, "app_id": self.app_id}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            print(f"Error sending Intercom message: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listening for Intercom messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
