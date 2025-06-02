import requests
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class ZulipConnector(BaseConnector):
    """Simple connector for sending messages to Zulip streams."""

    id = "zulip"
    name = "Zulip"

    def __init__(self, email: str, api_key: str, site_url: str, stream: str, topic: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.email = email
        self.api_key = api_key
        self.site_url = site_url.rstrip("/")
        self.stream = stream
        self.topic = topic

    def send_message(self, text: str) -> Optional[str]:
        url = f"{self.site_url}/api/v1/messages"
        data = {
            "type": "stream",
            "to": self.stream,
            "topic": self.topic,
            "content": text,
        }
        try:
            resp = requests.post(url, data=data, auth=(self.email, self.api_key))
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            self.logger.error("Error sending Zulip message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for Zulip messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message

    def is_connected(self) -> bool:
        url = f"{self.site_url}/api/v1/server_settings"
        try:
            resp = requests.get(url, auth=(self.email, self.api_key))
            resp.raise_for_status()
            return True
        except requests.RequestException:
            return False
