from typing import Any, Optional

from .base_connector import BaseConnector


class ACARSConnector(BaseConnector):
    """Connector for ACARS data link messages."""

    id = "acars"
    name = "ACARS"

    def __init__(self, host: str, port: int = 429, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.sent_messages: list[str] = []

    async def send_message(self, message: str) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for ACARS messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
