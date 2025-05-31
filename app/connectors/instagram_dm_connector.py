from .base_connector import BaseConnector


class InstagramDMConnector(BaseConnector):
    """Connector for Instagram direct messages."""

    id = "instagram_dm"
    name = "Instagram DM"

    def __init__(self, access_token: str, user_id: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.user_id = user_id
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for Instagram DM messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
