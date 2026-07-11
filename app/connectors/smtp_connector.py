import smtplib
from email.message import EmailMessage
from typing import Optional

from .base_connector import BaseConnector


class SMTPConnector(BaseConnector):
    """Connector for sending emails via SMTP."""

    id = "smtp"
    name = "SMTP"

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        from_address: str = "",
        to_address: str = "",
        use_tls: bool = True,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.to_address = to_address
        self.use_tls = use_tls
        self.server: Optional[smtplib.SMTP] = None

    def connect(self) -> None:
        self.server = smtplib.SMTP(self.host, self.port)
        if self.use_tls:
            self.server.starttls()
        if self.username:
            self.server.login(self.username, self.password)

    def disconnect(self) -> None:
        if self.server:
            try:
                self.server.quit()
            finally:
                self.server = None

    async def send_message(self, message: str) -> Optional[str]:
        if not self.server:
            self.connect()
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = self.to_address
        msg["Subject"] = "Norman Notification"
        msg.set_content(message)
        self.server.send_message(msg)
        return "sent"

    async def listen_and_process(self):
        """SMTP connector does not support incoming messages."""
        return None

    async def process_incoming(self, message):
        if not isinstance(message, dict):
            text = str(message)
            summary = f"smtp • {text}" if text else "smtp"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["smtp"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {"text": text, "text_summary": summary}

    def is_connected(self) -> bool:
        # State-based connectivity: callers can invoke `connect()` (implicitly
        # via `send_message`) and `disconnect()` to manage lifetime.
        return self.server is not None
