"""WhatsApp connector implemented using the Twilio API."""

import asyncio
import hmac
import hashlib
import base64
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class WhatsAppConnector(BaseConnector):
    """Connector for sending and receiving WhatsApp messages via Twilio."""

    id = "whatsapp"
    name = "WhatsApp"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        status_callback_url: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number
        self.status_callback_url = status_callback_url

    def _url(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"

    async def send_message(self, text: str) -> Optional[str]:
        """Send ``text`` to the configured WhatsApp number via Twilio."""
        data = {
            "From": f"whatsapp:{self.from_number}",
            "To": f"whatsapp:{self.to_number}",
            "Body": text,
        }
        if self.status_callback_url:
            data["StatusCallback"] = self.status_callback_url
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._url(), data=data, auth=(self.account_sid, self.auth_token)
                )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending WhatsApp message: %s", exc)
            return None

    async def listen_and_process(self) -> Optional[list]:
        """Fetch recent messages from Twilio and process them."""

        params = {
            "From": f"whatsapp:{self.to_number}",
            "To": f"whatsapp:{self.from_number}",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self._url(), params=params, auth=(self.account_sid, self.auth_token)
                )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error fetching WhatsApp messages: %s", exc)
            return None

        results = []
        for msg in payload.get("messages", []):
            processed = self.process_incoming(msg)
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                results.append(processed)
        return results

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize the incoming Twilio message payload."""
        text = message.get("Body") or message.get("body", "")
        sender = message.get("From") or message.get("from")
        to = message.get("To") or message.get("to", self.to_number)
        sid = message.get("MessageSid") or message.get("sid")

        summary_parts = ["whatsapp"]
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
        """Return ``True`` if the Twilio credentials appear valid."""

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}.json"
        try:
            resp = httpx.get(url, auth=(self.account_sid, self.auth_token))
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def set_webhook(self, webhook_url: str) -> bool:
        """Configure Twilio WhatsApp webhook for the sending number."""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/IncomingPhoneNumbers.json"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=(self.account_sid, self.auth_token))
            resp.raise_for_status()
            numbers = resp.json().get("incoming_phone_numbers", [])
            target = None
            from_number = self.from_number
            if not from_number.startswith("whatsapp:"):
                from_number = f"whatsapp:{from_number}"
            for item in numbers:
                if item.get("phone_number") == from_number:
                    target = item
                    break
            if not target:
                return False
            target_url = target.get("uri")
            if not target_url:
                return False
            update_url = f"https://api.twilio.com{target_url}"
            payload = {
                "SmsUrl": webhook_url,
                "SmsMethod": "POST",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    update_url, data=payload, auth=(self.account_sid, self.auth_token)
                )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error setting WhatsApp webhook: %s", exc)
            return False

    def verify_signature(self, signature: str, url: str, form: Dict[str, Any]) -> bool:
        """Validate a Twilio webhook signature."""
        if not signature or not self.auth_token:
            return False
        data = url + "".join(f"{k}{v}" for k, v in sorted(form.items()))
        digest = hmac.new(
            self.auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)
