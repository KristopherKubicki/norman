"""Connector for publishing messages using OPC UA PubSub."""

from typing import Any, Optional

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
        self.sent_messages: list[Any] = []
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
        """Listening for OPC UA messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound OPC UA messages
        return message
