import socket
from typing import Any, List

from .base_connector import BaseConnector


class XMPPConnector(BaseConnector):
    """Simple connector for XMPP servers."""

    id = "xmpp"
    name = "XMPP"

    def __init__(self, jid: str, password: str, server: str, config=None):
        super().__init__(config)
        self.jid = jid
        self.password = password
        self.server = server
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening to XMPP messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""
        if not isinstance(message, dict):
            text = str(message)
            return {
                "text": text,
                "text_summary": f"xmpp • {text}" if text else "xmpp",
            }
        text = message.get("body") or message.get("text") or ""
        sender = message.get("from") or message.get("sender")
        summary_parts = ["xmpp"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": sender,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the server is reachable."""
        if not super().is_connected():
            return False
        try:
            host, port = self.server, 5222
            if ":" in self.server:
                host, port_str = self.server.rsplit(":", 1)
                port = int(port_str)
            with socket.create_connection((host, port), timeout=5):
                return True
        except Exception:
            return False
