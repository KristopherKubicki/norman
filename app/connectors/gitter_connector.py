from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class GitterConnector(BaseConnector):
    """Connector for interacting with Gitter rooms."""

    id = "gitter"
    name = "Gitter"

    def __init__(self, token: str, room_id: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.token = token
        self.room_id = room_id

    async def send_message(self, text: str) -> Optional[str]:
        url = f"https://api.gitter.im/v1/rooms/{self.room_id}/chatMessages"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"text": text}, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network error
            logger.error("Error sending message to Gitter: %s", exc)
            return None

    async def listen_and_process(self) -> None:  # pragma: no cover - not implemented
        """Listening for Gitter messages is not implemented."""
        return None

    async def process_incoming(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"text": str(payload)}
        text = payload.get("text") or payload.get("message") or ""
        user = (payload.get("fromUser") or {}).get("username") or payload.get("user")
        summary_parts = ["gitter"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "user": user,
            "message_id": payload.get("id"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the token can access the room."""
        if not super().is_connected():
            return False
        try:
            url = f"https://api.gitter.im/v1/rooms/{self.room_id}"
            resp = httpx.get(
                url, headers={"Authorization": f"Bearer {self.token}"}, timeout=10
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
