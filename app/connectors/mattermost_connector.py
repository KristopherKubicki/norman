import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class MattermostConnector(BaseConnector):
    """Connector for Mattermost servers."""

    id = "mattermost"
    name = "Mattermost"

    def __init__(self, url: str, token: str, channel_id: str, config: Optional[dict] = None):
        super().__init__(config)
        self.url = url.rstrip("/")
        self.token = token
        self.channel_id = channel_id
        self.sent_messages = []

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured channel."""

        api_url = f"{self.url}/api/v4/posts"
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"channel_id": self.channel_id, "message": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error sending Mattermost message: {exc}")
                return None

    async def listen_and_process(self):
        """Listening for Mattermost messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the incoming ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the token appears valid."""

        api_url = f"{self.url}/api/v4/users/me"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = httpx.get(api_url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
