from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from .base_connector import BaseConnector


class SlackConnector(BaseConnector):

    def __init__(self, token: str, channel_id: str):
        self.token = token
        self.channel_id = channel_id
        self.client = WebClient(token=self.token)

    def connect(self):
        pass  # No need for a separate connect method, as WebClient will handle it.

    def disconnect(self):
        pass  # No need for a separate disconnect method, as WebClient will handle it.

    def listen_and_process(self):
        # Implement the method to listen for incoming messages and process them
        pass

    def process_incoming(self, payload: dict):
        # Implement the method to process an incoming payload
        pass

    def send_message(self, channel, message):
        try:
            response = self.client.chat_postMessage(channel=channel, text=message)
            return response
        except SlackApiError as e:
            print(f"Error sending message: {e}")

    def receive_message(self):
        pass  # This method is not applicable in this context, as the Slack API is not based on a continuous stream.

    def is_connected(self):
        try:
            self.client.auth_test()
            return True
        except SlackApiError:
            return False
