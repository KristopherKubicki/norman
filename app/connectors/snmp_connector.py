"""Connector for sending SNMP traps."""

import socket
from typing import Optional

from .base_connector import BaseConnector


class SNMPConnector(BaseConnector):
    """Minimal connector that emits SNMP traps over UDP."""

    id = "snmp"
    name = "SNMP"

    def __init__(self, host: str, port: int = 162, community: str = "public", config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.community = community
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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
            print(f"Error sending SNMP trap: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listening for traps is not implemented."""
        return None

    async def process_incoming(self, message: str) -> str:
        return message
