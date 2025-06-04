from .base_connector import BaseConnector
from typing import Any

class KikConnector(BaseConnector):
    """Stub connector for the Kik messaging platform."""

    id = "kik"
    name = "Kik"

    def __init__(self, username: str, api_key: str, config=None) -> None:
        super().__init__(config)
        self.username = username
        self.api_key = api_key
        self.sent_messages = []

    async def send_message(self, message: Any) -> str:
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
