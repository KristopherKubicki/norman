from .base_connector import BaseConnector


class DingTalkConnector(BaseConnector):
    """Connector for Alibaba DingTalk chat messages."""

    id = "dingtalk"
    name = "DingTalk"

    def __init__(self, access_token: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for DingTalk messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
