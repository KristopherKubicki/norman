import asyncio
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from .base_connector import BaseConnector


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
            messages = await asyncio.to_thread(self.receive_message)
        except SlackApiError as exc:
            print(f"Error receiving messages: {exc}")
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
                print(f"Error processing message: {exc}")
        return results

    def process_incoming(self, payload: dict):
        """Extract the useful fields from a Slack event payload."""
        if not isinstance(payload, dict):
            print("Invalid payload type")
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
            print(f"Error sending message: {e}")

    def receive_message(self):
        """Retrieve the most recent message from the Slack channel."""
        try:
            response = self.client.conversations_history(
                channel=self.channel_id, limit=1
            )
            return response.get("messages", [])
        except SlackApiError as e:
            print(f"Error receiving message: {e}")
            return []

    def is_connected(self):
        try:
            self.client.auth_test()
            return True
        except SlackApiError:
            return False
