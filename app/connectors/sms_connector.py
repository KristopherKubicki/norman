import base64
import hashlib
import hmac
from typing import Any, Dict, Optional
import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


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

    async def send_message(self, text: str) -> Optional[str]:
        data = {
            "From": self.from_number,
            "To": self.to_number,
            "Body": text,
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._url(), data=data, auth=(self.account_sid, self.auth_token)
                )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending SMS: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Twilio delivers incoming SMS via webhooks."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"text": str(message)}
        text = message.get("Body") or message.get("body") or ""
        sender = message.get("From") or message.get("from")
        to = message.get("To") or message.get("to") or self.to_number
        sid = message.get("MessageSid") or message.get("sid")
        summary_parts = ["sms"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "from": sender,
            "to": to,
            "sid": sid,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if Twilio credentials appear valid."""
        if not super().is_connected():
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}.json"
        try:
            resp = httpx.get(url, auth=(self.account_sid, self.auth_token))
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    def verify_signature(self, signature: str, url: str, form: Dict[str, Any]) -> bool:
        """Validate a Twilio webhook signature for inbound SMS."""
        if not signature or not self.auth_token:
            return False
        data = url + "".join(f"{k}{v}" for k, v in sorted(form.items()))
        digest = hmac.new(
            self.auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)
