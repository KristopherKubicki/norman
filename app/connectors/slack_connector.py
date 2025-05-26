from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from .base_connector import BaseConnector


class SlackConnector(BaseConnector):

    id = 'slack'
    name = 'Slack'

    def __init__(self, token: str, channel_id: str):
        self.token = token
        self.channel_id = channel_id
        self.client = WebClient(token=self.token)

    def connect(self):
        pass  # No need for a separate connect method, as WebClient will handle it.

    def disconnect(self):
        pass  # No need for a separate disconnect method, as WebClient will handle it.

    def listen_and_process(self):
        """Poll for messages in the configured channel and process them.

        Returns a list of processed messages. Any SlackApiError raised while
        retrieving or processing messages is caught and logged to stdout.
        """
        try:
            messages = self.receive_message()
        except SlackApiError as e:
            print(f"Error receiving messages: {e}")
            return []

        results = []
        for message in messages:
            try:
                processed = self.process_incoming(message)
                if processed:
                    results.append(processed)
            except Exception as e:  # pylint: disable=broad-except
                print(f"Error processing message: {e}")
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

    def send_message(self, channel, message):
        try:
            response = self.client.chat_postMessage(channel=channel, text=message)
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
