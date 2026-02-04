"""Connector for Google Chat using a service account."""

import os
import time
import httpx
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class GoogleChatConnector(BaseConnector):
    id = "google_chat"
    name = "Google Chat"

    def __init__(self, service_account_key_path: str, space: str, config=None):
        super().__init__(config)
        self.service_account_key_path = service_account_key_path
        self.space = space
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    def _get_access_token(self) -> str:
        if self._access_token and self._token_expiry:
            if time.time() < self._token_expiry - 60:
                return self._access_token

        if os.path.exists(self.service_account_key_path):
            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_key_path,
                scopes=["https://www.googleapis.com/auth/chat.bot"],
            )
            credentials.refresh(GoogleAuthRequest())
            self._access_token = credentials.token
            if credentials.expiry:
                self._token_expiry = credentials.expiry.timestamp()
            else:
                self._token_expiry = time.time() + 3000
            return self._access_token

        # Fallback: treat the configured value as a raw access token.
        return self.service_account_key_path

    async def send_message(self, message: str) -> Optional[str]:
        """Send ``message`` to the configured Google Chat space."""
        url = f"https://chat.googleapis.com/v1/{self.space}/messages"
        headers = {"Authorization": f"Bearer {self._get_access_token()}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json={"text": message}, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Google Chat message: %s", exc)
                return None

    def is_connected(self) -> bool:
        """Return ``True`` if the token can access the space."""
        url = f"https://chat.googleapis.com/v1/{self.space}"
        headers = {"Authorization": f"Bearer {self._get_access_token()}"}
        try:
            resp = httpx.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def listen_and_process(self) -> None:
        """Listening for Google Chat messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message
