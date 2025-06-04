from .base_connector import BaseConnector
from typing import Any

class PinterestConnector(BaseConnector):
    """Stub connector for the Pinterest API."""

    id = "pinterest"
    name = "Pinterest"

    def __init__(self, access_token: str, board_id: str, config=None) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.board_id = board_id
        self.sent_messages = []

    async def send_message(self, message: Any) -> str:
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
