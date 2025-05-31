from .base_connector import BaseConnector


class BlueskyConnector(BaseConnector):
    """Connector for posting to Bluesky."""

    id = "bluesky"
    name = "Bluesky"

    def __init__(self, handle: str, app_password: str, config=None):
        super().__init__(config)
        self.handle = handle
        self.app_password = app_password

    async def send_message(self, message):
        # Placeholder for sending a post to Bluesky
        pass

    async def listen_and_process(self):
        # Listening not implemented for Bluesky yet
        pass

    async def process_incoming(self, message):
        # Placeholder for processing inbound Bluesky messages
        pass
