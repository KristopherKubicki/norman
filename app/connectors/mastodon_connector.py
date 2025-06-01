from typing import Any, Dict, Optional

import requests
import httpx

from .base_connector import BaseConnector


class MastodonConnector(BaseConnector):
    """Connector for posting messages to a Mastodon server."""

    id = "mastodon"
    name = "Mastodon"

    def __init__(self, base_url: str, access_token: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def send_message(self, text: str) -> Optional[str]:
        url = f"{self.base_url}/api/v1/statuses"
        try:
            resp = requests.post(url, headers=self._headers(), data={"status": text})
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error sending message to Mastodon: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listen to the public streaming API and process events."""

        stream_url = f"{self.base_url}/api/v1/streaming"
        params = {"stream": "public"}

        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "GET", stream_url, headers=self._headers(), params=params
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        await self.process_incoming({"event": line})
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error listening to Mastodon stream: {exc}")

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
