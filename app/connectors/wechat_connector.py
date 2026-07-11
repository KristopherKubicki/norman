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
        """Normalize incoming WeChat payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}
        text = message.get("Content") or message.get("content") or ""
        sender = message.get("FromUserName") or message.get("from")
        recipient = message.get("ToUserName") or message.get("to")
        msg_type = message.get("MsgType") or message.get("type")
        summary_parts = ["wechat"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": sender,
            "recipient": recipient,
            "msg_type": msg_type,
            "timestamp": message.get("CreateTime"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the app credentials can get a token."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return "access_token" in data
        except httpx.HTTPError:
            return False
