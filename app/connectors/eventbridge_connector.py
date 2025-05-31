import json
from typing import Any, Dict, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    BotoCoreError = ClientError = Exception

from .base_connector import BaseConnector


class EventBridgeConnector(BaseConnector):
    """Connector that sends events to AWS EventBridge."""

    id = "eventbridge"
    name = "AWS EventBridge"

    def __init__(
        self,
        event_bus_name: str,
        source: str = "norman",
        region_name: str = "us-east-1",
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.event_bus_name = event_bus_name
        self.source = source
        if boto3:
            self.client = boto3.client(
                "events",
                region_name=region_name,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
            )
        else:  # pragma: no cover
            self.client = None

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        entry = {
            "EventBusName": self.event_bus_name,
            "Source": self.source,
            "DetailType": message.get("detail_type", "NormanEvent"),
            "Detail": json.dumps(message.get("detail", {})),
        }
        try:
            resp = self.client.put_events(Entries=[entry])
            return str(resp)
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover
            print(f"Error sending event to EventBridge: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """EventBridge connector does not receive messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
