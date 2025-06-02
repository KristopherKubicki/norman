"""Minimal Matrix connector leveraging the client-server API."""

import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)

class MatrixConnector(BaseConnector):
    """Connector for interacting with Matrix chat networks."""

    id = 'matrix'
    name = 'Matrix'

    def __init__(self, homeserver: str, user_id: str, access_token: str, room_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.room_id = room_id
        self._send_url = f"{self.homeserver}/_matrix/client/v3/rooms/{self.room_id}/send/m.room.message"
        self._next_batch: Optional[str] = None

    async def send_message(self, message):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"msgtype": "m.text", "body": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self._send_url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Matrix message: %s", exc)
                return None

    async def listen_and_process(self):
        """Long-poll the sync API and dispatch new messages."""

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            while True:  # pragma: no cover - loop runs until cancelled
                params = {"timeout": 30000}
                if self._next_batch:
                    params["since"] = self._next_batch
                try:
                    resp = await client.get(
                        f"{self.homeserver}/_matrix/client/v3/sync",
                        params=params,
                        headers=headers,
                        timeout=35,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as exc:  # pragma: no cover - network
                    logger.error("Matrix sync failed: %s", exc)
                    await asyncio.sleep(5)
                    continue

                self._next_batch = data.get("next_batch")
                events = (
                    data.get("rooms", {})
                    .get("join", {})
                    .get(self.room_id, {})
                    .get("timeline", {})
                    .get("events", [])
                )
                for event in events:
                    if event.get("type") != "m.room.message":
                        continue
                    content = event.get("content", {})
                    body = content.get("body", "")
                    result = self.process_incoming(body)
                    if asyncio.iscoroutine(result):
                        await result
                await asyncio.sleep(1)

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the access token is valid."""

        url = f"{self.homeserver}/_matrix/client/v3/account/whoami"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
