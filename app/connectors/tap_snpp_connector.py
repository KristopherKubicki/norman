from typing import Any, List, Optional

import asyncio

from .base_connector import BaseConnector


class TAPSNPPConnector(BaseConnector):
    """Connector for TAP/SNPP paging services."""

    id = "tap_snpp"
    name = "TAP/SNPP"

    def __init__(
        self,
        host: str,
        port: int = 444,
        password: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.password = password
        self.sent_messages: List[str] = []
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        """Establish a TCP connection to the TAP/SNPP service."""

        try:
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            if self.password:
                self._writer.write(f"PASS {self.password}\r\n".encode())
                await self._writer.drain()
        except OSError:
            self._reader = None
            self._writer = None

    async def disconnect(self) -> None:
        """Close any open TCP connection."""

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            finally:
                self._reader = None
                self._writer = None

    async def send_message(self, message: str) -> str:
        """Send ``message`` over TCP and record it locally."""

        self.sent_messages.append(message)
        if self._writer is None:
            await self.connect()
        if self._writer is not None:
            try:
                self._writer.write(f"PAGE {message}\r\n".encode())
                await self._writer.drain()
            except OSError:
                await self.disconnect()
        return "sent"

    async def listen_and_process(self) -> None:
        # TAP/SNPP connectors are typically outbound only
        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message

    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()
