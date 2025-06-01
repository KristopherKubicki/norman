"""Base connector class used by all connector implementations."""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseConnector(ABC):

    def __init__(self, config: Optional[dict] = None) -> None:
        """Initialize the connector with optional configuration."""

        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._send_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._dispatcher_task: Optional[asyncio.Task] = None
    async def connect(self) -> None:  # pragma: no cover - default no-op
        """Establish any connection required by the connector."""

    async def disconnect(self) -> None:  # pragma: no cover - default no-op
        """Disconnect and clean up resources."""

    @abstractmethod
    def send_message(self, message: Any) -> Any:
        """Send ``message`` to the remote service."""

    @abstractmethod
    async def listen_and_process(self) -> None:
        """Listen for incoming messages and pass them to :meth:`process_incoming`."""

    @abstractmethod
    async def process_incoming(self, message: Any) -> Any:
        """Handle an incoming message from the service."""

    async def queue_message(self, message: Any) -> None:
        """Queue ``message`` to be sent asynchronously."""

        await self._send_queue.put(message)

    async def _dispatcher(self) -> None:
        """Background task that sends queued messages."""

        while True:
            msg = await self._send_queue.get()
            try:
                result = self.send_message(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Failed to send message")
            finally:
                self._send_queue.task_done()

    async def run(self) -> None:
        """Connect, dispatch queued messages, and listen indefinitely."""

        connect_result = self.connect()
        if asyncio.iscoroutine(connect_result):
            await connect_result

        self._dispatcher_task = asyncio.create_task(self._dispatcher())
        try:
            await self.listen_and_process()
        finally:
            if self._dispatcher_task:
                self._dispatcher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._dispatcher_task
            disconnect_result = self.disconnect()
            if asyncio.iscoroutine(disconnect_result):
                await disconnect_result

    def is_connected(self) -> bool:  # pragma: no cover - default implementation
        """Return ``True`` if the connector appears to be healthy."""

        return True

