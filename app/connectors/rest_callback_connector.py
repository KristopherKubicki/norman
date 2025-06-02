import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class RESTCallbackConnector(BaseConnector):
    """Connector that forwards messages to a REST endpoint."""

    id = "rest_callback"
    name = "REST Callback"

    def __init__(self, callback_url: str, config=None) -> None:
        super().__init__(config)
        self.callback_url = callback_url

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Send a message to the configured callback URL."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.callback_url, json=message)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                self.logger.error(
                    "Error sending message to %s: %s", self.callback_url, exc
                )
                return None

    async def listen_and_process(self) -> None:
        """Continuously poll for messages from the callback URL."""

        last: Optional[str] = None
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    resp = await client.get(
                        self.callback_url,
                        params={"since": last} if last else None,
                    )
                    resp.raise_for_status()
                    messages = resp.json() if resp.content else []
                except httpx.HTTPError as exc:
                    self.logger.error("Error polling %s: %s", self.callback_url, exc)
                    await asyncio.sleep(30)
                    continue

                if isinstance(messages, dict):
                    messages = [messages]
                for msg in messages:
                    last = msg.get("id", last)
                    result = self.process_incoming(msg)
                    if asyncio.iscoroutine(result):
                        await result

                await asyncio.sleep(30)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Forward an incoming message to the callback URL."""
        await self.send_message(message)
        return message
