import asyncio
import httpx
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


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
            print(f"Error sending message to Salesforce: {exc}")
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
                    print(f"Error fetching Salesforce records: {exc}")
                    await asyncio.sleep(30)
                    continue

                for record in data:
                    last_id = record.get("Id")
                    result = self.process_incoming(record)
                    if asyncio.iscoroutine(result):
                        await result

                await asyncio.sleep(30)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
