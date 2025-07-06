"""Connector for sending messages over NATS or JetStream."""

import asyncio
from typing import Optional

try:
    import nats
except ImportError:  # pragma: no cover - optional dependency
    nats = None  # type: ignore

from .base_connector import BaseConnector


class NATSConnector(BaseConnector):
    """Minimal connector using ``nats-py``."""

    id = "nats"
    name = "NATS/JetStream"

    def __init__(
        self,
        servers: str = "nats://127.0.0.1:4222",
        subject: str = "norman",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.servers = servers
        self.subject = subject
        self._nc: Optional[nats.NATS] = None if nats else None

    async def connect(self) -> None:
        if not nats:
            raise RuntimeError("nats-py not installed")
        self._nc = await nats.connect(servers=self.servers)
        self._sid = None

    async def disconnect(self) -> None:
        if self._nc:
            if self._sid is not None:
                await self._nc.unsubscribe(self._sid)
                self._sid = None
            await self._nc.drain()
            await self._nc.close()
            self._nc = None

    async def send_message(self, message: str) -> Optional[str]:
        if not nats:
            raise RuntimeError("nats-py not installed")
        if not self._nc:
            await self.connect()
        assert self._nc is not None
        await self._nc.publish(self.subject, message.encode())
        return "ok"

    async def listen_and_process(self) -> None:
        """Subscribe to ``subject`` and process incoming messages indefinitely."""

        if not nats:
            raise RuntimeError("nats-py not installed")
        if not self._nc:
            await self.connect()

        async def _callback(msg):
            payload = msg.data.decode()
            result = self.process_incoming(payload)
            if asyncio.iscoroutine(result):
                await result

        assert self._nc is not None
        self._sid = await self._nc.subscribe(self.subject, cb=_callback)
        while True:  # pragma: no cover - run forever
            await asyncio.sleep(3600)

    async def process_incoming(self, message: str) -> str:
        return message
