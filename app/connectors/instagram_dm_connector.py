from .base_connector import BaseConnector


class InstagramDMConnector(BaseConnector):
    """Connector for Instagram direct messages."""

    id = "instagram_dm"
    name = "Instagram DM"

    def __init__(self, access_token: str, user_id: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.user_id = user_id

    async def send_message(self, message):
        # Placeholder for sending a message via Instagram DM
        pass

    async def listen_and_process(self):
        # Placeholder for listening for Instagram DM messages
        pass

    async def process_incoming(self, message):
        # Placeholder for processing inbound Instagram DM messages
        pass
