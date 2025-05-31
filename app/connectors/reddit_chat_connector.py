from .base_connector import BaseConnector


class RedditChatConnector(BaseConnector):
    """Connector for Reddit Chat."""

    id = "reddit_chat"
    name = "Reddit Chat"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        user_agent: str,
        config=None,
    ):
        super().__init__(config)
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.user_agent = user_agent
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening to Reddit Chat messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
