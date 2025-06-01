from typing import Any, List, Optional

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
        self.handle = None
        self.sent_messages: List[str] = []

    async def send_message(self, message: str) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for AX.25 messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
