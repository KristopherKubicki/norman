"""Minimal connector for the decentralized Tox messenger network."""

import asyncio
import importlib
from typing import Any, Optional, List

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)

try:  # pragma: no cover - optional dependency
    toxcore = importlib.import_module("toxcore")
except ImportError:  # pragma: no cover - tox library may be absent
    toxcore = None  # type: ignore


class ToxConnector(BaseConnector):
    """Connector using the ``toxcore`` Python bindings if available."""

    id = "tox"
    name = "Tox"

    def __init__(
        self,
        bootstrap_host: str,
        bootstrap_port: int = 33445,
        friend_id: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.bootstrap_host = bootstrap_host
        self.bootstrap_port = bootstrap_port
        self.friend_id = friend_id
        self.sent_messages: List[Any] = []
        self._tox = None
        self._friend_number: Optional[int] = None

    def connect(self) -> None:
        if toxcore is None:
            raise RuntimeError("toxcore not installed")
        tox_cls = getattr(toxcore, "Tox", None) or getattr(toxcore, "ToxCore", None)
        if tox_cls is None:
            raise RuntimeError("toxcore library missing Tox class")
        self._tox = tox_cls()
        self._tox.bootstrap(self.bootstrap_host, self.bootstrap_port, self.friend_id)
        if self.friend_id:
            self._friend_number = self._tox.add_friend(self.friend_id)
        self._tox.callback_friend_message(self._on_message)

    def disconnect(self) -> None:
        self._tox = None
        self._friend_number = None

    async def send_message(self, message: Any) -> str:
        if toxcore is None:
            raise RuntimeError("toxcore not installed")
        if not self._tox:
            self.connect()
        assert self._tox is not None
        if self._friend_number is None and self.friend_id:
            self._friend_number = self._tox.add_friend(self.friend_id)
        self._tox.friend_send_message(self._friend_number, message)
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        if toxcore is None:
            raise RuntimeError("toxcore not installed")
        if not self._tox:
            self.connect()
        assert self._tox is not None
        while True:  # pragma: no cover - loop runs until cancelled
            self._tox.iterate()
            await asyncio.sleep(0.1)

    async def process_incoming(self, message: Any) -> Any:
        return message

    def _on_message(self, _tox, friend_number, message) -> None:
        try:
            result = self.process_incoming(message)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Error processing Tox message from %s", friend_number)
