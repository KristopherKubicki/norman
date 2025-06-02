from typing import Optional

try:
    import aprslib
except ImportError:  # pragma: no cover - library optional
    aprslib = None

from .base_connector import BaseConnector


class APRSConnector(BaseConnector):
    """Connector for sending and receiving APRS packets via APRS-IS."""

    id = "aprs"
    name = "APRS"

    def __init__(
        self,
        host: str,
        port: int = 14580,
        callsign: str = "N0CALL",
        passcode: str = "00000",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.callsign = callsign
        self.passcode = passcode
        if aprslib:
            self.client = aprslib.IS(callsign, passwd=passcode, host=host, port=port)
        else:
            self.client = None

    async def send_message(self, message: str) -> None:
        if not aprslib:
            raise RuntimeError("aprslib not installed")
        self.client.connect()
        try:
            self.client.sendall(message)
        finally:
            self.client.close()

    async def listen_and_process(self) -> None:
        if not aprslib:
            raise RuntimeError("aprslib not installed")
        self.client.connect()
        try:
            for msg in self.client:
                await self.process_incoming(msg)
        finally:
            self.client.close()

    async def process_incoming(self, message):
        self.logger.error("APRS received: %s", message)
