"""Simple Discord connector using the HTTP API."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class DiscordConnector(BaseConnector):

    id = "discord"
    name = "Discord"

    def __init__(self, token: str, channel_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.channel_id = channel_id

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Discord channel."""
        url = f"https://discord.com/api/v9/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url, json={"content": message}, headers=headers
                )
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error sending Discord message: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """Listening for Discord messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""
        url = "https://discord.com/api/v9/users/@me"
        headers = {"Authorization": f"Bot {self.token}"}
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
