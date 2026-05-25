import asyncio
from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class PinterestConnector(BaseConnector):
    """Connector for posting pins via the Pinterest REST API."""

    id = "pinterest"
    name = "Pinterest"

    def __init__(
        self, access_token: str, board_id: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.access_token = access_token
        self.board_id = board_id
        self.api_url = "https://api.pinterest.com/v5"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Create a new pin on ``board_id`` using the provided ``message``."""
        payload = {
            "board_id": self.board_id,
            "title": message.get("title", ""),
            "description": message.get("description", ""),
        }
        if "image_url" in message:
            payload["media_source"] = {
                "source_type": "image_url",
                "url": message["image_url"],
            }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.api_url}/pins", json=payload, headers=self._headers()
                )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error creating Pinterest pin: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Pinterest does not offer polling for incoming messages."""
        logger.info("Pinterest connector does not support incoming messages")
        await asyncio.sleep(0)

    async def process_incoming(self, message: Any) -> Any:
        if not isinstance(message, dict):
            return {"text": str(message)}
        text = message.get("title") or message.get("description") or ""
        summary_parts = ["pinterest"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "pin_id": message.get("id"),
            "board_id": message.get("board_id"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the access token is valid."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"{self.api_url}/user_account",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
