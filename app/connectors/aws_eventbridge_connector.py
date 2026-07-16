"""Connector for sending events to AWS EventBridge."""

import json
from typing import Any, Dict, Optional

try:
    import boto3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None

from .base_connector import BaseConnector


def _is_configured_value(value: Optional[str]) -> bool:
    """Return whether an AWS setting is a real configured value."""

    return bool(value and value.strip() and not value.strip().startswith("your_"))


class AWSEventBridgeConnector(BaseConnector):
    """Simple connector using boto3's EventBridge client."""

    id = "aws_eventbridge"
    name = "AWS EventBridge"

    def __init__(
        self, region: str, event_bus_name: str, config: Optional[dict] = None
    ) -> None:
        super().__init__(config)
        self.region = region
        self.event_bus_name = event_bus_name
        if boto3 and _is_configured_value(self.region):
            self.client = boto3.client("events", region_name=self.region)
        else:  # pragma: no cover - dependency may be missing
            self.client = None

    async def send_message(self, message: Dict[str, Any]) -> Any:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        if self.client is None:
            raise RuntimeError("AWS EventBridge region is not configured")
        entry = {
            "Source": "norman",
            "DetailType": "message",
            "Detail": json.dumps(message),
            "EventBusName": self.event_bus_name,
        }
        return self.client.put_events(Entries=[entry])

    def is_connected(self) -> bool:
        """Return ``True`` if the configured event bus is reachable."""
        if not boto3 or self.client is None:
            return False
        try:
            self.client.describe_event_bus(Name=self.event_bus_name)
            return True
        except Exception:  # pragma: no cover - network/permission issues
            return False

    async def listen_and_process(self) -> None:
        """EventBridge does not support listening for messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"text": str(message)}
        detail = message.get("detail") or {}
        text = (
            detail.get("message") or message.get("detail-type") or "EventBridge event"
        )
        summary_parts = ["eventbridge"]
        if message.get("detail-type"):
            summary_parts.append(str(message.get("detail-type")))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "detail_type": message.get("detail-type"),
            "source": message.get("source"),
            "resources": message.get("resources"),
            "text_summary": summary,
        }
