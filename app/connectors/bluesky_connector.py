"""Bluesky connector using the AT Protocol APIs."""

from datetime import datetime, timezone
from typing import Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class BlueskyConnector(BaseConnector):
    """Connector for posting to Bluesky using app passwords."""

    id = "bluesky"
    name = "Bluesky"

    def __init__(
        self,
        handle: str,
        app_password: str,
        service_url: Optional[str] = "https://bsky.social",
        config=None,
    ) -> None:
        super().__init__(config)
        self.handle = handle
        self.app_password = app_password
        self.service_url = (service_url or "https://bsky.social").rstrip("/")
        self._access_jwt: Optional[str] = None
        self.sent_messages = []

    async def _login(self) -> Optional[str]:
        url = f"{self.service_url}/xrpc/com.atproto.server.createSession"
        payload = {"identifier": self.handle, "password": self.app_password}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                self._access_jwt = data.get("accessJwt")
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error logging in to Bluesky: %s", exc)
                return None
        return self._access_jwt

    async def send_message(self, message: str) -> Optional[str]:
        """Post ``message`` to Bluesky and return the response text."""
        token = self._access_jwt or await self._login()
        if not token:
            return None
        url = f"{self.service_url}/xrpc/com.atproto.repo.createRecord"
        payload = {
            "repo": self.handle,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": message,
                "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Bluesky message: %s", exc)
                return None

    async def listen_and_process(self):
        """Listening not implemented for Bluesky yet."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
