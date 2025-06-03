"""Stub connector for sending messages to Flowdock."""

from typing import Any, Optional, List

from .base_connector import BaseConnector


class FlowdockConnector(BaseConnector):
    """Minimal implementation for Flowdock."""

    id = "flowdock"
    name = "Flowdock"

    def __init__(self, api_token: str, flow: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.api_token = api_token
        self.flow = flow
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self) -> None:
        """Listening for Flowdock messages is not implemented."""
        return None

    async def process_incoming(self, message: Any) -> Any:
        return message
