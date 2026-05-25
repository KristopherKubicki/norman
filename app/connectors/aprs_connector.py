from typing import Optional

try:
    import aprslib
except ImportError:  # pragma: no cover - library optional
    aprslib = None

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


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
        if not isinstance(message, dict):
            text = str(message)
            logger.info("APRS received: %s", text)
            summary = f"aprs • {text}" if text else "aprs"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("comment") or ""
        summary_parts = ["aprs"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "source": message.get("source"),
            "destination": message.get("destination"),
            "path": message.get("path"),
            "latitude": message.get("latitude"),
            "longitude": message.get("longitude"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the connector is configured."""
        return super().is_connected()
