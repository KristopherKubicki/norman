"""Connector for sending messages to Flowdock flows."""

from typing import Any, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class FlowdockConnector(BaseConnector):
    """Interact with Flowdock using the push API."""

    id = "flowdock"
    name = "Flowdock"

    def __init__(
        self, api_token: str, flow: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.api_token = api_token
        self.flow = flow
        self.api_url = f"https://api.flowdock.com/v1/messages/chat/{flow}"

    async def send_message(self, message: Any) -> Optional[str]:
        """POST ``message`` to the Flowdock push API."""
        data = {"event": "message", "content": str(message)}
        params = {"flow_token": self.api_token}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.api_url, params=params, json=data)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Flowdock message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Flowdock messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        """Check if the Flowdock flow is reachable."""
        url = f"https://api.flowdock.com/v1/flows/{self.flow}"
        params = {"flow_token": self.api_token}
        try:
            resp = httpx.get(url, params=params, timeout=5)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
