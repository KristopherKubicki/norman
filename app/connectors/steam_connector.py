from .base_connector import BaseConnector


class SteamConnector(BaseConnector):
    """Connector for interacting with Steam Chat."""

    id = 'steam'
    name = 'Steam Chat'

    def __init__(self, api_key: str, chat_id: str, config=None):
        super().__init__(config)
        self.api_key = api_key
        self.chat_id = chat_id

    async def send_message(self, message):
        # Placeholder implementation for sending a message via Steam Chat
        pass

    async def listen_and_process(self):
        # Placeholder implementation for listening for incoming messages
        pass

    async def process_incoming(self, message):
        # Placeholder for processing an incoming Steam Chat message
        pass
