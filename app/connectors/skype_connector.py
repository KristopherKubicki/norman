from .base_connector import BaseConnector


class SkypeConnector(BaseConnector):
    """Connector for Skype."""

    id = "skype"
    name = "Skype"

    def __init__(self, app_id: str, app_password: str, config=None):
        super().__init__(config)
        self.app_id = app_id
        self.app_password = app_password
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for Skype messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
