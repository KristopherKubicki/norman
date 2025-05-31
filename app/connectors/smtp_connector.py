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

    async def send_message(self, message: str) -> None:
        if not self.server:
            self.connect()
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = self.to_address
        msg["Subject"] = "Norman Notification"
        msg.set_content(message)
        self.server.send_message(msg)

    async def listen_and_process(self):
        """SMTP connector does not support incoming messages."""
        return None

    async def process_incoming(self, message):
        return message

    def is_connected(self) -> bool:
        return self.server is not None
