"""Connector for sending messages over CoAP secured with OSCORE."""

from typing import Any, List, Optional

import asyncio
from asyncio import DatagramTransport

from .base_connector import BaseConnector


class CoAPOSCOREConnector(BaseConnector):
    """Minimal placeholder connector for CoAP + OSCORE."""

    id = "coap_oscore"
    name = "CoAP + OSCORE"

    def __init__(self, host: str, port: int = 5684, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.sent_messages: List[Any] = []
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

    async def send_message(self, message: Any) -> str:
        """Send ``message`` via UDP and record it locally."""

        self.sent_messages.append(message)
        if self._transport is None:
            await self.connect()
        if self._transport:
            try:
                self._transport.sendto(str(message).encode("utf-8"))
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
            local_addr=("0.0.0.0", self.port),
        )
        try:
            await asyncio.Future()
        finally:
            transport.close()

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound CoAP messages
        return message
