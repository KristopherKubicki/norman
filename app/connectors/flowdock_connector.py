"""Connector for sending messages to Flowdock using the REST API."""

from typing import Any, Optional, List

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class FlowdockConnector(BaseConnector):
    """Minimal implementation for Flowdock."""

    id = "flowdock"
    name = "Flowdock"

    def __init__(self, api_token: str, flow: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.api_token = api_token
        self.flow = flow
        self.sent_messages: List[Any] = []
        self.api_url = f"https://api.flowdock.com/flows/{self.flow}/messages"

    async def send_message(self, message: Any) -> Optional[str]:
        """POST ``message`` to Flowdock and record it."""
        headers = {"Authorization": f"Bearer {self.api_token}"}
        payload = {"event": "message", "content": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Flowdock message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Flowdock messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
