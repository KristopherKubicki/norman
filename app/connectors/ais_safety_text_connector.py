"""Connector for AIS safety-related text messages (VDM 6/12)."""

from typing import Any, Optional

from .base_connector import BaseConnector


class AISSafetyTextConnector(BaseConnector):
    """Placeholder connector for AIS VDM 6/12 messages."""

    id = "ais_safety_text"
    name = "AIS Safety-Related Text"

    def __init__(self, host: str, port: int = 12345, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.sent_messages: list[str] = []

    async def send_message(self, message: str) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for AIS messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
