from .base_connector import BaseConnector


class DingTalkConnector(BaseConnector):
    """Connector for Alibaba DingTalk chat messages."""

    id = "dingtalk"
    name = "DingTalk"

    def __init__(self, access_token: str, config=None):
        super().__init__(config)
        self.access_token = access_token
        self.sent_messages = []

    async def send_message(self, message) -> str:
        """Record ``message`` locally and return a confirmation string."""
        self.sent_messages.append(message)
        return "sent"

    async def listen_and_process(self):
        """Listening for DingTalk messages is not implemented."""
        return None

    async def process_incoming(self, message):
        """Return the incoming ``message`` payload."""
        if not isinstance(message, dict):
            text = str(message)
            summary = f"dingtalk • {text}" if text else "dingtalk"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["dingtalk"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "sender": message.get("sender"),
            "conversation_id": message.get("conversationId")
            or message.get("conversation_id"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the connector is configured."""
        return super().is_connected()
