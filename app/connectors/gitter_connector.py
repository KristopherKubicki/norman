from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector


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
            print(f"Error sending message to Gitter: {exc}")
            return None

    async def listen_and_process(self) -> None:  # pragma: no cover - not implemented
        """Listening for Gitter messages is not implemented."""
        return None

    async def process_incoming(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload
