import requests
from typing import Any, Dict, Optional
from .base_connector import BaseConnector


class TelegramConnector(BaseConnector):

    id = "telegram"
    name = "Telegram"

    def __init__(self, token: str, chat_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.chat_id = chat_id

    def _send_request(self, data: Dict[str, Any]) -> Optional[str]:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error while sending message to Telegram: {e}")
            return None

        return response.text

    def send_message(self, text: str) -> Optional[str]:
        data = {"chat_id": self.chat_id, "text": text}

        return self._send_request(data)

    async def listen_and_process(self) -> None:
        """Listening for Telegram updates is not implemented."""
        return None

    def process_incoming(self, payload: Dict[str, Any]) -> Dict[str, str]:
        message = payload.get("message", {})
        text = message.get("text", "")
        return {"text": text, "channel": "Telegram"}

    def set_webhook(self, webhook_url: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/setWebhook"
        try:
            response = requests.post(url, json={"url": webhook_url})
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error while setting webhook for Telegram: {e}")
            return False

        return True

    def is_connected(self) -> bool:
        """Return ``True`` if the bot token is valid."""
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return bool(data.get("ok"))
        except requests.exceptions.RequestException:
            return False
