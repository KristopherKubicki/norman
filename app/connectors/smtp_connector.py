import asyncio
import smtplib
from email.mime.text import MIMEText
from .base_connector import BaseConnector


class SMTPConnector(BaseConnector):
    """A simple connector for sending messages via SMTP."""

    id = "smtp"
    name = "SMTP Email"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addr: str,
        config=None,
    ):
        super().__init__(config)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addr = to_addr

    async def send_message(self, message: dict):
        """Send an email using the configured SMTP server."""
        msg = MIMEText(message.get("text", ""))
        msg["Subject"] = message.get("subject", "")
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr

        await asyncio.to_thread(self._send, msg)

    def _send(self, msg: MIMEText):
        with smtplib.SMTP(self.host, self.port) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.from_addr, [self.to_addr], msg.as_string())

    async def listen_and_process(self):
        # Receiving email is not implemented
        pass

    async def process_incoming(self, message):
        pass
