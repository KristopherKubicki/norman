import httpx
from .base_connector import BaseConnector


class SkypeConnector(BaseConnector):
    """Connector for Skype."""

    id = "skype"
    name = "Skype"

    def __init__(self, app_id: str, app_password: str, config=None):
        super().__init__(config)
        self.app_id = app_id
        self.app_password = app_password
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for Skype messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        if not isinstance(message, dict):
            text = str(message)
            summary = f"skype • {text}" if text else "skype"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["skype"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": message.get("from"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the app credentials can get a token."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.post(
                "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                data={
                    "client_id": self.app_id,
                    "client_secret": self.app_password,
                    "grant_type": "client_credentials",
                    "scope": "https://api.botframework.com/.default",
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
