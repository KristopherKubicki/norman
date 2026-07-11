"""Connector for syslog-style passive notes over UDP.

This is intentionally lightweight: it does not attempt full RFC3164/5424
parsing. The goal is to turn "something happened" packets into routable
passive signals.

Defaults:
- Listens on unprivileged UDP port 1514 (privileged 514 requires root).
- In listen mode, outbound send is disabled unless target_host/target_port is
  explicitly configured.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Optional

from app.core.logging import setup_logger

from .base_connector import BaseConnector

logger = setup_logger(__name__)

_LOCAL_LISTEN_HOSTS = {"0.0.0.0", "127.0.0.1", "localhost"}


class SyslogConnector(BaseConnector):
    id = "syslog"
    name = "Syslog"

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 1514,
        listen: Optional[bool] = None,
        target_host: str = "",
        target_port: int = 514,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = (host or "").strip() or "0.0.0.0"
        self.port = int(port)
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
            self._sock.bind((self.host, self.port))
        else:
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

        if self._should_listen():
            if not self.target_host:
                return "ignored"
            dest = (self.target_host, self.target_port)
        else:
            dest = (self.host, self.port)

        try:
            self._sock.sendto(payload, dest)
            return "ok"
        except OSError as exc:  # pragma: no cover
            logger.error("Error sending syslog message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        if not self._should_listen():
            while True:  # pragma: no cover
                await asyncio.sleep(60)

        if not self._sock:
            self.connect()
        assert self._sock is not None

        self._sock.setblocking(False)
        while True:  # pragma: no cover
            try:
                data, addr = self._sock.recvfrom(8192)
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
            summary = f"syslog{addr_note} • {text}" if text else "syslog"
        else:
            text = message if isinstance(message, str) else str(message)
            summary = f"syslog • {text}" if text else "syslog"

        return {
            "text": text,
            "text_summary": summary,
            "signal_class": "passive",
            "passive_source": "syslog",
            "sensor_type": "syslog",
        }

    def is_connected(self) -> bool:
        if not super().is_connected():
            return False
        if self._should_listen():
            return True
        try:
            socket.gethostbyname(self.host)
            return True
        except socket.error:
            return False
