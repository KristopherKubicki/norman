from .base_connector import BaseConnector


class WeChatConnector(BaseConnector):
    """Connector for WeChat."""

    id = "wechat"
    name = "WeChat"

    def __init__(self, app_id: str, app_secret: str, config=None):
        super().__init__(config)
        self.app_id = app_id
        self.app_secret = app_secret
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Store ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for WeChat messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
