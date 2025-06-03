"""Stub connector for Atlassian HipChat rooms."""

from typing import Any, Optional, List

from .base_connector import BaseConnector


class HipChatConnector(BaseConnector):
    """Minimal implementation for HipChat."""

    id = "hipchat"
    name = "HipChat"

    def __init__(self, token: str, room_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.token = token
        self.room_id = room_id
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for HipChat messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
