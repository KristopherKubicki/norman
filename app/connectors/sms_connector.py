from typing import Any, Dict, Optional
import requests

from .base_connector import BaseConnector


class SMSConnector(BaseConnector):
    """Connector for sending SMS messages via Twilio."""

    id = "sms"
    name = "SMS"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number

    def _url(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"

    def send_message(self, text: str) -> Optional[str]:
        data = {
            "From": self.from_number,
            "To": self.to_number,
            "Body": text,
        }
        try:
            resp = requests.post(self._url(), data=data, auth=(self.account_sid, self.auth_token))
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            self.logger.error("Error sending SMS: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Twilio delivers incoming SMS via webhooks."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
