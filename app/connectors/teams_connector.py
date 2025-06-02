"""Connector for sending messages to Microsoft Teams via a bot endpoint."""

import importlib
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class TeamsConnector(BaseConnector):

    id = "teams"
    name = "Teams"

    def __init__(self, app_id, app_password, tenant_id, bot_endpoint, config=None):
        super().__init__(config)
        self.app_id = app_id
        self.app_password = app_password
        self.tenant_id = tenant_id
        self.bot_endpoint = bot_endpoint

    async def send_message(self, message: str) -> Optional[str]:
        """POST ``message`` to the configured bot endpoint."""
        headers = {"Authorization": f"Bearer {self.app_password}"}
        httpx = importlib.import_module("httpx")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self.bot_endpoint, json={"text": message}, headers=headers
                )
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending Teams message: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        """Listening for Teams messages is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw ``message`` payload."""
        return message

    def is_connected(self) -> bool:
        """Return ``True`` if the bot endpoint is reachable."""
        headers = {"Authorization": f"Bearer {self.app_password}"}
        httpx = importlib.import_module("httpx")
        try:
            resp = httpx.get(self.bot_endpoint, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
