"""Connector for sending events via PagerDuty Events v2 API."""

from typing import Any, Dict, Optional

import requests

from .base_connector import BaseConnector


class PagerDutyConnector(BaseConnector):
    """Connector that triggers PagerDuty incidents."""

    id = "pagerduty"
    name = "PagerDuty Events v2"

    def __init__(self, routing_key: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.routing_key = routing_key
        self.api_url = "https://events.pagerduty.com/v2/enqueue"

    def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        payload = {
            "routing_key": self.routing_key,
            "event_action": message.get("event_action", "trigger"),
            "payload": {
                "summary": message.get("summary", "Norman Event"),
                "source": message.get("source", "norman"),
                "severity": message.get("severity", "info"),
            },
        }
        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error sending PagerDuty event: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Listening is not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
