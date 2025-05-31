from .base_connector import BaseConnector


class LinkedInConnector(BaseConnector):
    """Connector for LinkedIn Messaging."""

    id = "linkedin"
    name = "LinkedIn"

    def __init__(self, access_token: str, config=None):
        super().__init__(config)
        self.access_token = access_token

    async def send_message(self, message):
        # Placeholder for sending a LinkedIn message
        pass

    async def listen_and_process(self):
        # Placeholder for listening to LinkedIn messages
        pass

    async def process_incoming(self, message):
        # Placeholder for processing inbound LinkedIn messages
        pass
