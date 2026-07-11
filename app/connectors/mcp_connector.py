"""Connector for sending events to a generic MCP HTTP service."""

import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class MCPConnector(BaseConnector):
    """Connector for interacting with an MCP service."""

    id = "mcp"
    name = "MCP"

    def __init__(
        self, api_url: str, api_key: str, config: Optional[dict] = None
    ) -> None:
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
                logger.error("Error sending message to MCP: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Poll the MCP service for inbound events."""

        last: Optional[str] = None
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    resp = await client.get(
                        self.api_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        params={"since": last} if last else None,
                    )
                    resp.raise_for_status()
                    messages = resp.json() if resp.content else []
                except httpx.HTTPError as exc:
                    logger.error("Error fetching MCP events: %s", exc)
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
        if not isinstance(message, dict):
            text = str(message)
            summary = f"mcp • {text}" if text else "mcp"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["mcp"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {"text": text, "text_summary": summary}

    def is_connected(self) -> bool:
        """Return ``True`` if the API is reachable."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            if resp.status_code >= 500:
                return False
            return True
        except httpx.HTTPError:
            return False
