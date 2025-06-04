from .base_connector import BaseConnector
from typing import Any

class GroupMeConnector(BaseConnector):
    """Stub connector for the GroupMe messaging service."""

    id = "groupme"
    name = "GroupMe"

    def __init__(self, bot_id: str, config=None) -> None:
        super().__init__(config)
        self.bot_id = bot_id
        self.sent_messages = []

    async def send_message(self, message: Any) -> str:
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
