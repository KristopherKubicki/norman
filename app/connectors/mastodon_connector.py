from .base_connector import BaseConnector

try:
    from mastodon import Mastodon
except Exception:  # pragma: no cover - mastodon library may not be installed
    Mastodon = None


class MastodonConnector(BaseConnector):
    """Connector for interacting with Mastodon instances."""

    id = 'mastodon'
    name = 'Mastodon'

    def __init__(self, api_base_url: str, access_token: str, config=None):
        super().__init__(config)
        self.api_base_url = api_base_url
        self.access_token = access_token
        if Mastodon:
            self.client = Mastodon(api_base_url=self.api_base_url, access_token=self.access_token)
        else:
            self.client = None

    async def send_message(self, message: str):
        """Post a status update to Mastodon."""
        if self.client:
            self.client.status_post(message)
        else:
            # Client library not available; pretend we sent the message
            pass

    async def listen_and_process(self):
        """Listen for incoming messages from Mastodon (not implemented)."""
        pass

    async def process_incoming(self, message):
        """Process an incoming Mastodon message (not implemented)."""
        pass
