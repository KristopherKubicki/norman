"""Connector for interacting with X.com direct messages via Tweepy."""

import asyncio
import importlib
from typing import Any, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class XComConnector(BaseConnector):
    """Connector for X.com direct messages."""

    id = "xcom"
    name = "X.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
        recipient_id: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.recipient_id = recipient_id
        self._client = None
        self._last_message_id: Optional[str] = None

    def _get_client(self):
        if self._client is None:
            tweepy = importlib.import_module("tweepy")
            auth = tweepy.OAuth1UserHandler(
                self.api_key,
                self.api_secret,
                self.access_token,
                self.access_token_secret,
            )
            self._client = tweepy.API(auth)
        return self._client

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to ``recipient_id`` using Tweepy."""
        tweepy = importlib.import_module("tweepy")
        client = self._get_client()
        try:
            client.send_direct_message(self.recipient_id, text=message)
            return "sent"
        except tweepy.TweepyException as exc:  # pragma: no cover - network
            logger.error("Error sending X.com message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Poll for new direct messages and process them."""
        tweepy = importlib.import_module("tweepy")
        client = self._get_client()
        while True:  # pragma: no cover - loop runs until cancelled
            try:
                messages = client.list_direct_messages()
            except tweepy.TweepyException as exc:  # pragma: no cover - network
                logger.error("Error fetching X.com messages: %s", exc)
                await asyncio.sleep(5)
                continue

            for msg in reversed(messages):
                msg_id = msg.get("id")
                if self._last_message_id and msg_id <= self._last_message_id:
                    continue
                self._last_message_id = msg_id
                result = self.process_incoming(msg)
                if asyncio.iscoroutine(result):
                    await result
            await asyncio.sleep(5)

    async def process_incoming(self, message: Any) -> Any:
        return message

    def is_connected(self) -> bool:
        tweepy = importlib.import_module("tweepy")
        client = self._get_client()
        try:
            client.verify_credentials()
            return True
        except tweepy.TweepyException:
            return False
