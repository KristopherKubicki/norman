"""Placeholder connector for the Tox peer-to-peer network."""

from typing import Any, Optional, List

from .base_connector import BaseConnector


class ToxConnector(BaseConnector):
    """Stub implementation for the Tox protocol."""

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

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for Tox messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        # Placeholder for processing inbound messages
        return message
