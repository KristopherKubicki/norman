"""Connector for sending syslog messages over TLS as defined in RFC 5425."""

import ssl
import socket
from typing import Optional

from .base_connector import BaseConnector


class RFC5425Connector(BaseConnector):
    """Simple connector for RFC 5425 TLS syslog servers."""

    id = "rfc5425"
    name = "RFC 5425 Syslog"

    def __init__(
        self,
        host: str,
        port: int = 6514,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        context = ssl.create_default_context()
        raw_sock = socket.create_connection((self.host, self.port))
        self._socket = context.wrap_socket(raw_sock, server_hostname=self.host)

    def disconnect(self) -> None:
        if self._socket:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def send_message(self, message: str) -> None:
        if not self._socket:
            self.connect()
        assert self._socket is not None  # mypy helper
        data = message.encode("utf-8")
        framed = f"{len(data)} ".encode("ascii") + data
        self._socket.sendall(framed)

    async def listen_and_process(self) -> None:
        """RFC 5425 is typically used for outbound logs only."""
        return None

    async def process_incoming(self, message):
        return message
