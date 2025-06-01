from typing import Any, List, Optional

from .base_connector import BaseConnector


class TAPSNPPConnector(BaseConnector):
    """Connector for TAP/SNPP paging services."""

    id = "tap_snpp"
    name = "TAP/SNPP"

    def __init__(self, host: str, port: int = 444, password: Optional[str] = None, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.password = password
        self.sent_messages: List[str] = []

    async def send_message(self, message: str) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        # TAP/SNPP connectors are typically outbound only
        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
