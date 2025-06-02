"""Connector for the Viber Bots API."""

from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector


class ViberConnector(BaseConnector):
    """Send messages to Viber using the Bots API."""

    id = "viber"
    name = "Viber Bots"

    def __init__(self, auth_token: str, receiver: str, config: Optional[dict] = None) -> None:
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
            print(f"Error sending Viber message: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listening for Viber messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
