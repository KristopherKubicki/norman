"""Connector for Apple Messages for Business."""

from typing import Any, Dict, Optional
import requests
from .base_connector import BaseConnector


class AppleMessagesBusinessConnector(BaseConnector):
    """Send messages via Apple Messages for Business."""

    id = "apple_messages_business"
    name = "Apple Messages for Business"

    def __init__(self, access_token: str, sender_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.sender_id = sender_id
        self.api_url = "https://api.apple.com/business/v1/messages"

    def send_message(self, text: str) -> Optional[str]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"sender": {"id": self.sender_id}, "message": {"text": text}}
        try:
            resp = requests.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error sending Apple Messages for Business: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listening for Apple Messages for Business is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
