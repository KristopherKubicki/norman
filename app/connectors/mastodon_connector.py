from typing import Any, Dict, Optional

import json

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


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

    async def send_message(self, text: str) -> Optional[str]:
        url = f"{self.base_url}/api/v1/statuses"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=self._headers(), data={"status": text})
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending message to Mastodon: %s", exc)
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
                    event: Dict[str, str] = {}
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if line == "":
                            if event:
                                await self.process_incoming(event)
                                event = {}
                            continue
                        if line.startswith(":"):
                            continue
                        if ":" in line:
                            key, value = line.split(":", 1)
                            event[key.strip()] = value.strip()
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error listening to Mastodon stream: %s", exc)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the parsed event with JSON decoded if possible."""
        data = message.get("data")
        if isinstance(data, str):
            try:
                message["data"] = json.loads(data)
            except ValueError:  # pragma: no cover - data may not be JSON
                pass
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the access token is valid."""

        url = f"{self.base_url}/api/v1/accounts/verify_credentials"
        try:
            resp = httpx.get(url, headers=self._headers())
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
