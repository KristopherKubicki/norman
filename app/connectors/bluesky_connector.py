from .base_connector import BaseConnector


class BlueskyConnector(BaseConnector):
    """Connector for posting to Bluesky."""

    id = "bluesky"
    name = "Bluesky"

    def __init__(self, handle: str, app_password: str, config=None):
        super().__init__(config)
        self.handle = handle
        self.app_password = app_password
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening not implemented for Bluesky yet."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
