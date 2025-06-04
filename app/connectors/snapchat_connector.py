"""Snapchat connector implemented using a hypothetical client library."""

import asyncio
import importlib
from typing import Any, List, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)

class SnapchatConnector(BaseConnector):
    """Connector for the Snapchat messaging service."""

    id = "snapchat"
    name = "Snapchat"

    def __init__(
        self,
        username: str,
        password: str,
        recipient: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.username = username
        self.password = password
        self.recipient = recipient
        self.sent_messages: List[Any] = []
        self._client = None

    def _get_client(self):
        """Lazily import and return the Snapchat client."""
        if self._client is None:
            snap_mod = importlib.import_module("snapchat")
            self._client = snap_mod.Client(self.username, self.password)
        return self._client

    async def send_message(self, message: Any) -> Optional[str]:
        """Send ``message`` to the configured ``recipient``."""

        client = self._get_client()
        snap_mod = importlib.import_module("snapchat")
        try:
            result = client.send(self.recipient, message)
            if asyncio.iscoroutine(result):
                await result
            self.sent_messages.append(message)
            return "sent"
        except snap_mod.SnapchatError as exc:  # pragma: no cover - network
            logger.error("Error sending Snapchat message: %s", exc)
            return None

    async def listen_and_process(self) -> List[Any]:
        """Fetch new messages and process them."""

        client = self._get_client()
        snap_mod = importlib.import_module("snapchat")
        try:
            messages = client.get_messages()
            if asyncio.iscoroutine(messages):
                messages = await messages
        except snap_mod.SnapchatError as exc:  # pragma: no cover - network
            logger.error("Error fetching Snapchat messages: %s", exc)
            return []

        results = []
        for msg in messages:
            processed = self.process_incoming(msg)
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                results.append(processed)
        return results

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if authentication appears valid."""

        client = self._get_client()
        try:
            return bool(client.logged_in())
        except Exception:  # pragma: no cover - client may raise various errors
            return False
