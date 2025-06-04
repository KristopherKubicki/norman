from .base_connector import BaseConnector
from typing import Any

class SnapchatConnector(BaseConnector):
    """Stub connector for the Snapchat messaging service."""

    id = "snapchat"
    name = "Snapchat"

    def __init__(self, username: str, password: str, config=None) -> None:
        super().__init__(config)
        self.username = username
        self.password = password
        self.sent_messages = []

    async def send_message(self, message: Any) -> str:
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
