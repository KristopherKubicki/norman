"""WhatsApp connector implemented using the Twilio API."""

import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)

class WhatsAppConnector(BaseConnector):
    """Connector for sending and receiving WhatsApp messages via Twilio."""

    id = 'whatsapp'
    name = 'WhatsApp'

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
        return (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        )

    async def send_message(self, text: str) -> Optional[str]:
        """Send ``text`` to the configured WhatsApp number via Twilio."""
        data = {
            "From": f"whatsapp:{self.from_number}",
            "To": f"whatsapp:{self.to_number}",
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

        return {
            "text": message.get("body", ""),
            "from": message.get("from"),
            "to": message.get("to", self.to_number),
            "sid": message.get("sid"),
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
