"""Connector for publishing messages using OPC UA PubSub."""

from typing import Any, List, Optional

import asyncio
from asyncio import DatagramTransport

from .base_connector import BaseConnector


class OPCUAPubSubConnector(BaseConnector):
    """Minimal connector for OPC UA PubSub over UDP."""

    id = "opcua_pubsub"
    name = "OPC UA PubSub"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: List[Any] = []
        self._transport: Optional[DatagramTransport] = None

    async def connect(self) -> None:
        """Create a UDP transport for outbound messages if possible."""
        target = self.endpoint.split("://")[-1]
        if ":" in target:
            host, port_str = target.split(":", 1)
            port = int(port_str)
        else:
            host, port = target, 4840
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(host, port),
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

        target = self.endpoint.split("://")[-1]
        if ":" in target:
            _, port_str = target.split(":", 1)
            port = int(port_str)
        else:
            port = 4840

        loop = asyncio.get_running_loop()

        class _Handler(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr):
                msg = data.decode("utf-8", errors="replace")
                asyncio.create_task(self_conn.process_incoming(msg))

        self_conn = self
        transport, _ = await loop.create_datagram_endpoint(
            _Handler,
            local_addr=("0.0.0.0", port),
        )
        try:
            await asyncio.Future()
        finally:
            transport.close()

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound OPC UA messages
        return message
