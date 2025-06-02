"""Connector for Google Business Messages / RCS."""

from typing import Any, Dict, Optional
import requests
from .base_connector import BaseConnector


class GoogleBusinessRCSConnector(BaseConnector):
    """Send messages using Google Business Messages (RCS)."""

    id = "google_business_rcs"
    name = "Google Business Messages / RCS"

    def __init__(self, access_token: str, phone_number: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.phone_number = phone_number
        self.api_url = "https://businessmessages.googleapis.com/v1"

    def send_message(self, text: str) -> Optional[str]:
        url = f"{self.api_url}/conversations/{self.phone_number}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"message": {"text": text}}
        try:
            resp = requests.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            self.logger.error("Error sending Google Business message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Google Business Messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
