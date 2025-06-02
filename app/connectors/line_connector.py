"""Connector for the LINE Messaging API."""

from typing import Any, Dict, Optional

import requests

from .base_connector import BaseConnector


class LineConnector(BaseConnector):
    """Send messages to LINE users via the Messaging API."""

    id = "line"
    name = "LINE Messaging"

    def __init__(self, channel_access_token: str, user_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.channel_access_token = channel_access_token
        self.user_id = user_id
        self.api_url = "https://api.line.me/v2/bot/message/push"

    def send_message(self, text: str) -> Optional[str]:
        headers = {"Authorization": f"Bearer {self.channel_access_token}"}
        payload = {"to": self.user_id, "messages": [{"type": "text", "text": text}]}
        try:
            resp = requests.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            self.logger.error("Error sending LINE message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening for LINE messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
