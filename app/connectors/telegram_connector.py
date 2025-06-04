import httpx
import asyncio
from typing import Any, Dict, Optional, List
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class TelegramConnector(BaseConnector):

    id = "telegram"
    name = "Telegram"

    def __init__(self, token: str, chat_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.chat_id = chat_id
        self._offset: Optional[int] = None

    async def _send_request(self, data: Dict[str, Any]) -> Optional[str]:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Error while sending message to Telegram: %s", e)
            return None

        return response.text

    async def send_message(self, text: str) -> Optional[str]:
        data = {"chat_id": self.chat_id, "text": text}

        return await self._send_request(data)

    async def listen_and_process(self) -> List[Dict[str, Any]]:
        """Poll the Telegram API for new updates and process them."""

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {"timeout": 30}
        if self._offset is not None:
            params["offset"] = self._offset

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, timeout=35)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as e:  # pragma: no cover - network
                logger.error("Error while fetching Telegram updates: %s", e)
                return []

        results: List[Dict[str, Any]] = []
        for update in data.get("result", []):
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = max(self._offset or 0, update_id + 1)
            processed = self.process_incoming(update)
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                results.append(processed)
        return results

    def process_incoming(self, payload: Dict[str, Any]) -> Dict[str, str]:
        message = payload.get("message", {})
        text = message.get("text", "")
        return {"text": text, "channel": "Telegram"}

    async def set_webhook(self, webhook_url: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/setWebhook"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json={"url": webhook_url})
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Error while setting webhook for Telegram: %s", e)
            return False

        return True

    def is_connected(self) -> bool:
        """Return ``True`` if the bot token is valid."""
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        try:
            response = httpx.get(url)
            response.raise_for_status()
            data = response.json()
            return bool(data.get("ok"))
        except httpx.HTTPError:
            return False
