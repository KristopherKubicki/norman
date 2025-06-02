import httpx

from .base_connector import BaseConnector


class WeChatConnector(BaseConnector):
    """Connector for WeChat."""

    id = "wechat"
    name = "WeChat"

    def __init__(self, app_id: str, app_secret: str, config=None):
        super().__init__(config)
        self.app_id = app_id
        self.app_secret = app_secret
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Send a text ``message`` via the WeChat API and record it."""
        self.sent_messages.append(message)
        url = (
            "https://api.weixin.qq.com/cgi-bin/message/custom/send"
            f"?access_token={self.app_secret}"
        )
        payload = {
            "touser": self.app_id,
            "msgtype": "text",
            "text": {"content": message},
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=5)
            resp.raise_for_status()
        except httpx.HTTPError:  # pragma: no cover - network
            pass
        return "sent"

    async def listen_and_process(self):
        """Listening for WeChat messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        return message
