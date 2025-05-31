from typing import Any

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
        self.sent_messages: list[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""

        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening to XMPP messages is not implemented."""

        return None

    async def process_incoming(self, message: Any) -> Any:
        """Return the incoming ``message`` payload."""

        return message
