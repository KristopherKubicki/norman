"""Connector for sending SNMP traps."""

import socket
import asyncio
from typing import Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class SNMPConnector(BaseConnector):
    """Minimal connector that emits SNMP traps over UDP."""

    id = "snmp"
    name = "SNMP"

    def __init__(
        self,
        host: str,
        port: int = 162,
        community: str = "public",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.community = community
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("", 0))

    def disconnect(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def send_message(self, message: str) -> Optional[str]:
        if not self._sock:
            self.connect()
        assert self._sock is not None
        payload = message.encode("utf-8")
        try:
            self._sock.sendto(payload, (self.host, self.port))
            return "ok"
        except OSError as exc:  # pragma: no cover - network errors
            logger.error("Error sending SNMP trap: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listen for inbound traps and process them indefinitely."""

        if not self._sock:
            self.connect()
        assert self._sock is not None
        self._sock.setblocking(False)
        while True:  # pragma: no cover - run forever
            try:
                data, _ = self._sock.recvfrom(4096)
            except BlockingIOError:
                await asyncio.sleep(0.1)
                continue
            message = data.decode("utf-8", "ignore")
            result = self.process_incoming(message)
            if asyncio.iscoroutine(result):
                await result

    async def process_incoming(self, message: str) -> str:
        return message
