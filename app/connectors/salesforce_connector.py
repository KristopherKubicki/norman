import requests
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

    def send_message(self, data: Dict[str, Any]) -> Optional[str]:
        url = f"{self.instance_url}/{self.endpoint}"
        try:
            resp = requests.post(url, json=data, headers=self._headers())
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error sending message to Salesforce: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Salesforce connector does not support inbound messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.send_message(message)
        return message
