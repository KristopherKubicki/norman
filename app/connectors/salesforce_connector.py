import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class SalesforceConnector(BaseConnector):
    """Simple connector for posting data to Salesforce REST endpoints."""

    id = "salesforce"
    name = "Salesforce"

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        endpoint: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.endpoint = endpoint.lstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def send_message(self, data: Dict[str, Any]) -> Optional[str]:
        url = f"{self.instance_url}/{self.endpoint}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=data, headers=self._headers())
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error sending message to Salesforce: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Poll Salesforce for changes if the Streaming API is available."""

        last_id: Optional[str] = None
        url = f"{self.instance_url}/services/data/v57.0/sobjects/{self.endpoint}"
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    resp = await client.get(
                        url,
                        headers=self._headers(),
                        params={"_lastid": last_id} if last_id else None,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("records", [])
                except httpx.HTTPError as exc:  # pragma: no cover - network
                    logger.error("Error fetching Salesforce records: %s", exc)
                    await asyncio.sleep(30)
                    continue

                for record in data:
                    last_id = record.get("Id")
                    result = self.process_incoming(record)
                    if asyncio.iscoroutine(result):
                        await result

                await asyncio.sleep(30)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Salesforce records or webhook payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        record_id = message.get("Id") or message.get("id")
        name = message.get("Name") or message.get("name")
        title = message.get("Title") or message.get("title") or name
        status = message.get("Status") or message.get("status")
        description = message.get("Description") or message.get("description") or ""

        summary_parts = ["salesforce"]
        if title:
            summary_parts.append(title)
        if status:
            summary_parts.append(status)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "record_id": record_id,
            "title": title,
            "status": status,
            "description": description,
            "text": title or description,
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the token can access the instance."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"{self.instance_url}/services/data",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
