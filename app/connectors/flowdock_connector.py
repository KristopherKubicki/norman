"""Connector for sending messages to Flowdock."""

from typing import Any, Optional, List

import httpx

from app.core.logging import setup_logger

from .base_connector import BaseConnector


logger = setup_logger(__name__)


class FlowdockConnector(BaseConnector):
    """Interact with Flowdock flows via the HTTP API."""

    id = "flowdock"
    name = "Flowdock"

    def __init__(
        self, api_token: str, flow: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.api_token = api_token
        self.flow = flow
        self.sent_messages: List[Any] = []
        self.base_url = "https://api.flowdock.com"

    async def send_message(self, message: str) -> str:
        """Send ``message`` to the configured Flowdock flow."""
        url = f"{self.base_url}/v1/messages/chat/{self.flow}"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        payload = {"content": message}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending Flowdock message: %s", exc)
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for Flowdock messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the API token appears valid."""

        url = f"{self.base_url}/user"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
