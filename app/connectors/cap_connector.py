"""Connector for sending alerts using the Common Alerting Protocol (CAP v1.2)."""

from typing import Any, Optional

from .base_connector import BaseConnector


class CAPConnector(BaseConnector):
    """Placeholder connector for CAP 1.2 messages."""

    id = "cap"
    name = "Common Alerting Protocol v1.2"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: list[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """CAP is typically outbound only."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
