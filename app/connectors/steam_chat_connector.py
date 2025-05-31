from .base_connector import BaseConnector


class SteamChatConnector(BaseConnector):
    """Connector for Steam Chat."""

    id = "steam_chat"
    name = "Steam Chat"

    def __init__(self, token: str, chat_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.chat_id = chat_id

    async def send_message(self, message):
        # Placeholder for sending a message to Steam Chat
        pass

    async def listen_and_process(self):
        # Placeholder for listening to Steam Chat messages
        pass

    async def process_incoming(self, message):
        # Placeholder for processing inbound Steam Chat messages
        pass
