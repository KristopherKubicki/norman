"""AX.25 connector implementation."""

from typing import Any, List, Optional

import asyncio
import socket

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
        self.handle: Optional[Any] = None
        self._sock: Optional[socket.socket] = None
        self.sent_messages: List[str] = []

    async def connect(self) -> None:
        """Open an AX.25 connection if possible."""

        if ax25:
            # Many ``pyax25`` implementations expose an ``AX25`` class
            # for interacting with a port.  We attempt to use it if
            # available, falling back to raw sockets otherwise.
            try:  # pragma: no cover - library optional
                self.handle = ax25.AX25(port=self.port, callsign=self.callsign)
                result = self.handle.open()  # type: ignore[attr-defined]
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception:  # pragma: no cover - best effort
                self.handle = None

        # Fallback to a basic AF_AX25 datagram socket when ``ax25`` is not
        # installed.  The address tuple format varies by kernel, so errors
        # are ignored.
        try:
            self._sock = socket.socket(socket.AF_AX25, socket.SOCK_DGRAM)
            self._sock.bind((self.callsign, 0, self.port))
        except OSError:  # pragma: no cover - environment specific
            self._sock = None

    async def disconnect(self) -> None:
        if self.handle is not None:
            try:  # pragma: no cover - library optional
                close_result = self.handle.close()  # type: ignore[attr-defined]
                if asyncio.iscoroutine(close_result):
                    await close_result
            finally:
                self.handle = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    async def send_message(self, message: str) -> str:
        """Send ``message`` over AX.25 when possible and record it locally."""

        self.sent_messages.append(message)

        if self.handle is None and self._sock is None:
            await self.connect()

        if self.handle is not None:
            try:  # pragma: no cover - library optional
                result = self.handle.send(message)  # type: ignore[attr-defined]
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - best effort
                pass
        elif self._sock is not None:
            try:
                self._sock.sendto(message.encode("utf-8"), (self.callsign, 0, self.port))
            except OSError:  # pragma: no cover - environment specific
                pass

        return "sent"

    async def listen_and_process(self) -> None:
        """Receive AX.25 frames and process them."""

        if self.handle is None and self._sock is None:
            await self.connect()

        if self.handle is not None:
            while True:  # pragma: no cover - run forever
                try:
                    frame = await asyncio.to_thread(self.handle.recv)  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover - best effort
                    await asyncio.sleep(1)
                    continue
                result = self.process_incoming(frame)
                if asyncio.iscoroutine(result):
                    await result
        elif self._sock is not None:
            loop = asyncio.get_running_loop()
            while True:  # pragma: no cover - run forever
                try:
                    data = await loop.sock_recv(self._sock, 1024)
                except OSError:  # pragma: no cover - environment specific
                    await asyncio.sleep(1)
                    continue
                message = data.decode("utf-8", errors="replace")
                result = self.process_incoming(message)
                if asyncio.iscoroutine(result):
                    await result

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
