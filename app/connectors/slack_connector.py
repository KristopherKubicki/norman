import asyncio
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class SlackConnector(BaseConnector):

    id = 'slack'
    name = 'Slack'

    def __init__(self, token: str, channel_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.channel_id = channel_id
        self.client = WebClient(token=self.token)

    def connect(self):
        pass  # No need for a separate connect method, as WebClient will handle it.

    def disconnect(self):
        pass  # No need for a separate disconnect method, as WebClient will handle it.

    async def listen_and_process(self):
        """Poll for messages asynchronously and process them."""

        try:
            loop = asyncio.get_running_loop()
            messages = await loop.run_in_executor(None, self.receive_message)
        except SlackApiError as exc:
            logger.error("Error receiving messages: %s", exc)
            return []

        results = []
        for message in messages:
            try:
                processed = self.process_incoming(message)
                if asyncio.iscoroutine(processed):
                    processed = await processed
                if processed:
                    results.append(processed)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error processing message: %s", exc)
        return results

    def process_incoming(self, payload: dict):
        """Extract the useful fields from a Slack event payload."""
        if not isinstance(payload, dict):
            logger.error("Invalid payload type")
            return {}

        return {
            "text": payload.get("text", ""),
            "user": payload.get("user"),
            "channel": payload.get("channel", self.channel_id),
            "ts": payload.get("ts"),
        }

    def send_message(self, message):
        try:
            response = self.client.chat_postMessage(channel=self.channel_id, text=message)
            return response
        except SlackApiError as e:
            logger.error("Error sending message: %s", e)

    def receive_message(self):
        """Retrieve the most recent message from the Slack channel."""
        try:
            response = self.client.conversations_history(
                channel=self.channel_id, limit=1
            )
            return response.get("messages", [])
        except SlackApiError as e:
            logger.error("Error receiving message: %s", e)
            return []

    def is_connected(self):
        try:
            self.client.auth_test()
            return True
        except SlackApiError:
            return False
