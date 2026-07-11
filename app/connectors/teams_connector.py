"""Connector for sending messages to Microsoft Teams via a bot endpoint."""

import importlib
import time
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class TeamsConnector(BaseConnector):
    id = "teams"
    name = "Teams"

    def __init__(
        self,
        app_id,
        app_password,
        tenant_id,
        bot_endpoint,
        webhook_url: Optional[str] = None,
        scope: Optional[str] = None,
        config=None,
    ):
        super().__init__(config)
        self.app_id = app_id
        self.app_password = app_password
        self.tenant_id = tenant_id
        self.bot_endpoint = bot_endpoint
        self.webhook_url = webhook_url
        self.scope = scope or "https://graph.microsoft.com/.default"
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    async def _get_access_token(self) -> Optional[str]:
        if self._access_token and self._token_expiry:
            if time.time() < self._token_expiry - 60:
                return self._access_token

        if not self.app_id or not self.app_password or not self.tenant_id:
            return None

        httpx = importlib.import_module("httpx")
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.app_id,
            "client_secret": self.app_password,
            "grant_type": "client_credentials",
            "scope": self.scope,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        self._token_expiry = time.time() + int(expires_in)
        return self._access_token

    async def send_message(self, message: str) -> Optional[str]:
        """POST ``message`` to the configured bot endpoint."""
        if self.webhook_url:
            headers = {}
            url = self.webhook_url
        else:
            token = await self._get_access_token()
            if not token:
                return None
            headers = {"Authorization": f"Bearer {token}"}
            url = self.bot_endpoint
        httpx = importlib.import_module("httpx")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json={"text": message}, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Teams message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Teams messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Teams webhook payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        text = message.get("text") or ""
        from_user = (message.get("from") or {}).get("name") or (
            message.get("from") or {}
        ).get("id")
        conversation = message.get("conversation") or {}
        channel = conversation.get("id")
        event_type = message.get("type") or "message"

        summary_parts = ["teams", event_type]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "event": event_type,
            "text": text,
            "user": from_user,
            "channel": channel,
            "service_url": message.get("serviceUrl"),
            "conversation": conversation,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the bot endpoint is reachable."""
        if self.webhook_url:
            headers = {}
            url = self.webhook_url
        else:
            if not self.app_id or not self.app_password or not self.tenant_id:
                return False
            headers = {}
            url = self.bot_endpoint
        httpx = importlib.import_module("httpx")
        try:
            resp = httpx.get(url, headers=headers)
            if resp.status_code >= 500:
                return False
            return True
        except httpx.HTTPError:
            return False
