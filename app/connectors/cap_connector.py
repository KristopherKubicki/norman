"""Connector for sending alerts using the Common Alerting Protocol (CAP v1.2)."""

from typing import Any, List, Optional

import httpx

from .base_connector import BaseConnector


class CAPConnector(BaseConnector):
    """Send CAP 1.2 messages to a remote HTTP endpoint."""

    id = "cap"
    name = "Common Alerting Protocol v1.2"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """POST ``message`` to the configured endpoint and record it."""

        self.sent_messages.append(message)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.endpoint, data=message)
                resp.raise_for_status()
            except httpx.HTTPError:  # pragma: no cover - network
                pass
        return "sent"

    async def listen_and_process(self) -> None:
        """CAP is typically outbound only."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
