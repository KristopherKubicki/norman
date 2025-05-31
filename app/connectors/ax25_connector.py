from typing import Optional

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

    async def send_message(self, message: str) -> None:
        # Placeholder for sending a message via AX.25
        pass

    async def listen_and_process(self) -> None:
        # Placeholder for listening for AX.25 messages
        pass

    async def process_incoming(self, message):
        # Placeholder for processing inbound AX.25 messages
        pass
