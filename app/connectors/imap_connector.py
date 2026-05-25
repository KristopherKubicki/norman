"""Connector for polling IMAP mailboxes."""

import asyncio
import imaplib
from email import message_from_bytes
from email.header import decode_header
from typing import Any, Dict, List, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class IMAPConnector(BaseConnector):
    id = "imap"
    name = "IMAP"

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        mailbox: str = "INBOX",
        use_ssl: bool = True,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self.use_ssl = use_ssl

    def _connect(self) -> imaplib.IMAP4:
        client = (
            imaplib.IMAP4_SSL(self.host, self.port)
            if self.use_ssl
            else imaplib.IMAP4(self.host, self.port)
        )
        if self.username:
            client.login(self.username, self.password)
        return client

    def _decode_header(self, value: Optional[str]) -> str:
        if not value:
            return ""
        parts = decode_header(value)
        decoded = ""
        for text, encoding in parts:
            if isinstance(text, bytes):
                decoded += text.decode(encoding or "utf-8", errors="ignore")
            else:
                decoded += text
        return decoded

    def _extract_body(self, message) -> str:
        body = ""
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                if content_type not in {"text/plain", "text/html"}:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                text = payload.decode(errors="ignore")
                if content_type == "text/plain":
                    return text
                if not body:
                    body = text
        else:
            payload = message.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="ignore")

        if "<" in body and ">" in body:
            body = " ".join(body.replace("\n", " ").split())
        return body

    async def listen_and_process(self) -> List[Dict[str, Any]]:
        """Poll for unseen emails and normalize them."""

        def _fetch() -> List[Dict[str, Any]]:
            results: List[Dict[str, Any]] = []
            client = self._connect()
            try:
                client.select(self.mailbox)
                status, data = client.search(None, "UNSEEN")
                if status != "OK":
                    return results
                for msg_id in data[0].split():
                    status, msg_data = client.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not msg_data:
                        continue
                    raw = msg_data[0][1]
                    msg = message_from_bytes(raw)
                    results.append(self.process_incoming(msg))
            finally:
                try:
                    client.logout()
                except Exception:
                    pass
            return results

        return await asyncio.to_thread(_fetch)

    def process_incoming(self, message) -> Dict[str, Any]:
        subject = self._decode_header(message.get("Subject"))
        sender = self._decode_header(message.get("From"))
        to = self._decode_header(message.get("To"))
        cc = self._decode_header(message.get("Cc"))
        date = self._decode_header(message.get("Date"))
        message_id = self._decode_header(message.get("Message-Id"))
        body = self._extract_body(message)

        summary_parts = ["email"]
        if subject:
            summary_parts.append(subject)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "subject": subject,
            "from": sender,
            "to": to,
            "cc": cc,
            "date": date,
            "message_id": message_id,
            "body": body,
            "text": body or subject,
            "text_summary": summary,
        }

    async def send_message(self, message: str) -> Optional[str]:
        """IMAP is inbound only."""
        return None

    def is_connected(self) -> bool:
        try:
            client = self._connect()
            client.select(self.mailbox)
            client.logout()
            return True
        except Exception:
            logger.exception("IMAP connection failed")
            return False
