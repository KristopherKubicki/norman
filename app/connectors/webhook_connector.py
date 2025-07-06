"""Simple connector that forwards messages to an HTTP webhook."""

import httpx
from fastapi import HTTPException
from typing import Any, Dict, Optional
from pydantic import BaseModel

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class WebhookConnector(BaseConnector):
    """Connector for sending messages to an HTTP webhook."""

    name = "Webhook"
    id = "webhook"

    def __init__(self, webhook_url: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.webhook_url = webhook_url
        self.enabled = True

    async def connect(self) -> None:  # pragma: no cover - no connection needed
        """Webhook connectors do not maintain persistent connections."""

    async def disconnect(self) -> None:  # pragma: no cover - no connection needed
        """Webhook connectors do not maintain persistent connections."""

    async def send_message(self, data: Dict[str, Any]) -> Optional[str]:
        """Send ``data`` to the configured webhook URL."""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.webhook_url, json=data)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending message to webhook: %s", exc)
                return None

    async def send_to_webhook(self, data: Dict[str, Any]) -> str:
        """Send ``data`` to the webhook and raise on error.

        This method wraps :meth:`send_message` but raises a
        :class:`~fastapi.HTTPException` if sending fails.  The extra
        error handling is useful for API routes that want to surface a
        failure as an HTTP error.
        """

        result = await self.send_message(data)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to send to webhook")
        return result

    async def listen_and_process(self) -> None:  # pragma: no cover - no incoming
        """Webhook connectors do not listen for inbound messages."""
        return None

    async def process_incoming(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Forward ``data`` to the webhook and return it."""

        await self.send_message(data)
        return data


class IncomingMessage(BaseModel):
    channel: str
    message: str
    user: str


async def process_webhook_message(message: IncomingMessage):
    webhook_connector = WebhookConnector("https://your-webhook-url.example.com/")
    response = await webhook_connector.process_incoming(message.dict())
    return response
