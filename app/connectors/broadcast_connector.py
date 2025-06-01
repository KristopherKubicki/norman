import asyncio
from typing import Any, List, Optional

from .base_connector import BaseConnector

class BroadcastConnector(BaseConnector):
    """Connector that forwards messages to multiple other connectors."""

    id = "broadcast"
    name = "Broadcast"

    def __init__(self, connectors: str = "", config: Optional[dict] = None) -> None:
        super().__init__(config)
        names = [c.strip() for c in connectors.split(",") if c.strip()]
        self.connector_names = [n for n in names if n and n != self.id]
        self.connectors: List[BaseConnector] = []
        from . import connector_utils  # local import to avoid circular dependency

        for name in self.connector_names:
            if name not in connector_utils.connector_classes:
                self.logger.warning("Unknown connector %s", name)
                continue
            try:
                self.connectors.append(connector_utils.get_connector(name))
            except Exception:  # pragma: no cover - constructor may fail
                self.logger.exception("Failed to initialize connector %s", name)

    async def connect(self) -> None:
        for conn in self.connectors:
            result = conn.connect()
            if asyncio.iscoroutine(result):
                await result

    async def disconnect(self) -> None:
        for conn in self.connectors:
            result = conn.disconnect()
            if asyncio.iscoroutine(result):
                await result

    def send_message(self, message: Any) -> Any:
        for conn in self.connectors:
            result = conn.send_message(message)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        return "sent"

    async def listen_and_process(self) -> None:
        """Broadcast connector does not listen for incoming messages."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        return all(getattr(c, "is_connected", lambda: True)() for c in self.connectors)
