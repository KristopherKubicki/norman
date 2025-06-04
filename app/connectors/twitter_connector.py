"""Connector for sending direct messages via the Twitter API."""

from typing import Any, Optional
import importlib

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class TwitterConnector(BaseConnector):
    """Connector for X.com (Twitter) direct messages."""

    id = "twitter"
    name = "X.com (Twitter)"

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
            logger.error("Error sending Twitter message: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening to Twitter messages is not implemented."""
        return None

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
