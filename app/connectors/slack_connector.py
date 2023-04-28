from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from base_connector import BaseConnector


class SlackConnector(BaseConnector):
    def __init__(self, config):
        super().__init__(config)
        self.client = WebClient(token=self.config["token"])

    def connect(self):
        pass  # No need for a separate connect method, as WebClient will handle it.

    def disconnect(self):
        pass  # No need for a separate disconnect method, as WebClient will handle it.

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
