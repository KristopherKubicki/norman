"""Connector for AIS safety-related text messages (VDM 6/12)."""

import asyncio
from typing import Any, List, Optional

from asyncio import DatagramTransport

from .base_connector import BaseConnector


class AISSafetyTextConnector(BaseConnector):
    """Minimal connector for AIS VDM 6/12 messages over UDP."""

    id = "ais_safety_text"
    name = "AIS Safety-Related Text"

    def __init__(self, host: str, port: int = 12345, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.sent_messages: List[str] = []
        self._transport: Optional[DatagramTransport] = None

    async def connect(self) -> None:
        """Create a UDP transport for outbound messages if possible."""
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(self.host, self.port),
            )
        except OSError:
            self._transport = None

    async def disconnect(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    async def send_message(self, message: str) -> str:
        """Send ``message`` via UDP and record it locally."""

        self.sent_messages.append(message)
        if self._transport is None:
            await self.connect()
        if self._transport:
            try:
                self._transport.sendto(message.encode("utf-8"))
            except OSError:
                pass
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for AIS messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
