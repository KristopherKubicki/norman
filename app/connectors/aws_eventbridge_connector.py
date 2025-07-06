"""Connector for sending events to AWS EventBridge."""

import json
from typing import Any, Dict, Optional

try:
    import boto3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None

from .base_connector import BaseConnector


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
        if boto3:
            self.client = boto3.client("events", region_name=self.region)
        else:  # pragma: no cover - dependency may be missing
            self.client = None

    async def send_message(self, message: Dict[str, Any]) -> Any:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        entry = {
            "Source": "norman",
            "DetailType": "message",
            "Detail": json.dumps(message),
            "EventBusName": self.event_bus_name,
        }
        return self.client.put_events(Entries=[entry])

    def is_connected(self) -> bool:
        """Return ``True`` if the configured event bus is reachable."""
        if not boto3:
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
        return message
