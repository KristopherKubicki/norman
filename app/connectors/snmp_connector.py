"""Connector for SNMP passive traps and optional outbound trap sends.

Design:
- Default to *listening* when configured like a sensor (host=0.0.0.0/localhost).
- Avoid privileged ports by default (1162 instead of 162).
- Outbound sends are supported when configured with a non-local host, or via
  target_host/target_port in listen mode.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Optional

from app.core.logging import setup_logger

from .base_connector import BaseConnector

logger = setup_logger(__name__)


_LOCAL_LISTEN_HOSTS = {"0.0.0.0", "127.0.0.1", "localhost"}


class SNMPConnector(BaseConnector):
    """Minimal connector for inbound SNMP trap notes over UDP."""

    id = "snmp"
    name = "SNMP"

    def __init__(
        self,
        host: str,
        port: int = 1162,
        community: str = "public",
        listen: Optional[bool] = None,
        target_host: str = "",
        target_port: int = 162,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = (host or "").strip() or "0.0.0.0"
        self.port = int(port)
        self.community = community
        self.listen = listen
        self.target_host = (target_host or "").strip()
        self.target_port = int(target_port)
        self._sock: Optional[socket.socket] = None

    def _should_listen(self) -> bool:
        if self.listen is not None:
            return bool(self.listen)
        return self.host.lower() in _LOCAL_LISTEN_HOSTS

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self._should_listen():
            # Bind to the configured host/port for passive traps.
            self._sock.bind((self.host, self.port))
        else:
            # Outbound sender socket.
            self._sock.bind(("", 0))

    def disconnect(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def send_message(self, message: str) -> Optional[str]:
        if not self._sock:
            self.connect()
        assert self._sock is not None

        text = message if isinstance(message, str) else str(message)
        payload = text.encode("utf-8")

        # In listen mode, only send if an explicit target is configured.
        if self._should_listen():
            if not self.target_host:
                return "ignored"
            dest = (self.target_host, self.target_port)
        else:
            dest = (self.host, self.port)

        try:
            self._sock.sendto(payload, dest)
            return "ok"
        except OSError as exc:  # pragma: no cover - network errors
            logger.error("Error sending SNMP trap: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listen for inbound traps and process them indefinitely."""

        if not self._should_listen():
            # Configured as sender; no inbound loop.
            while True:  # pragma: no cover
                await asyncio.sleep(60)

        if not self._sock:
            self.connect()
        assert self._sock is not None
        self._sock.setblocking(False)
        while True:  # pragma: no cover - run forever
            try:
                data, addr = self._sock.recvfrom(4096)
            except BlockingIOError:
                await asyncio.sleep(0.1)
                continue
            message = data.decode("utf-8", "ignore")
            result = self.process_incoming({"text": message, "addr": addr})
            if asyncio.iscoroutine(result):
                await result

    async def process_incoming(self, message) -> dict:
        text = ""
        if isinstance(message, dict):
            text = str(message.get("text") or "")
            addr = message.get("addr")
            addr_note = f" from {addr[0]}" if isinstance(addr, tuple) and addr else ""
            summary = f"snmp{addr_note} • {text}" if text else "snmp"
        else:
            text = message if isinstance(message, str) else str(message)
            summary = f"snmp • {text}" if text else "snmp"
        return {
            "text": text,
            "text_summary": summary,
            "signal_class": "passive",
            "passive_source": "snmp",
            "sensor_type": "snmp",
        }

    def is_connected(self) -> bool:
        if not super().is_connected():
            return False
        # For listeners, connectivity is basically "can bind"; for senders, host should resolve.
        if self._should_listen():
            return True
        try:
            socket.gethostbyname(self.host)
            return True
        except socket.error:
            return False
