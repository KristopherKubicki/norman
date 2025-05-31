"""Connector for sending events to a generic MCP HTTP service."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector

class MCPConnector(BaseConnector):
    """Connector for interacting with an MCP service."""

    id = 'mcp'
    name = 'MCP'

    def __init__(self, api_url: str, api_key: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """POST ``message`` to the MCP API."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self.api_url,
                    json=message,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                print(f"Error sending message to MCP: {exc}")
                return None

    async def listen_and_process(self) -> None:
        """This connector does not actively listen for events."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
