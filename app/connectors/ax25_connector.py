from typing import Any, List, Optional

import asyncio
from asyncio import DatagramTransport

try:
    import ax25
except ImportError:  # pragma: no cover - library optional
    ax25 = None

from .base_connector import BaseConnector


class AX25Connector(BaseConnector):
    """Connector for AX.25 packet radio."""

    id = "ax25"
    name = "AX.25"

    def __init__(
        self,
        port: str,
        callsign: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.port = port
        self.callsign = callsign
        self.handle = None
        self.sent_messages: List[str] = []
        self._transport: Optional[DatagramTransport] = None

    async def connect(self) -> None:
        """Create a UDP transport for outbound messages if possible."""
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=("127.0.0.1", 8001),
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
        """Listen for UDP datagrams and process them."""

        loop = asyncio.get_running_loop()

        class _Handler(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr):
                message = data.decode("utf-8", errors="replace")
                asyncio.create_task(self_conn.process_incoming(message))

        self_conn = self
        transport, _ = await loop.create_datagram_endpoint(
            _Handler,
            local_addr=("0.0.0.0", 8001),
        )
        try:
            await asyncio.Future()
        finally:
            transport.close()

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
