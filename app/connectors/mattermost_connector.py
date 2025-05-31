from .base_connector import BaseConnector


class MattermostConnector(BaseConnector):
    """Connector for Mattermost servers."""

    id = "mattermost"
    name = "Mattermost"

    def __init__(self, url: str, token: str, channel_id: str, config=None):
        super().__init__(config)
        self.url = url.rstrip("/")
        self.token = token
        self.channel_id = channel_id
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for Mattermost messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
