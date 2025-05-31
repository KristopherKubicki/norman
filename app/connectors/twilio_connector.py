from typing import Optional, Dict
import requests
from .base_connector import BaseConnector

class TwilioConnector(BaseConnector):
    """Connector for sending SMS messages via Twilio."""

    id = 'twilio'
    name = 'Twilio SMS'

    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str, config=None):
        super().__init__(config)
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number

    def _send_request(self, data: Dict[str, str]) -> Optional[str]:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        try:
            response = requests.post(url, data=data, auth=(self.account_sid, self.auth_token))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error while sending message via Twilio: {e}")
            return None
        return response.text

    async def send_message(self, text: str) -> Optional[str]:
        data = {
            "From": self.from_number,
            "To": self.to_number,
            "Body": text,
        }
        return self._send_request(data)

    async def listen_and_process(self):
        # Twilio SMS connectors typically rely on incoming webhooks.
        pass

    async def process_incoming(self, message):
        # Process an incoming SMS message payload.
        pass
