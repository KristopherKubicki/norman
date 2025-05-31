"""Connector for publishing messages to AWS IoT Core."""

from typing import Any, Dict, Optional

try:
    import boto3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None

from .base_connector import BaseConnector


class AWSIoTCoreConnector(BaseConnector):
    """Simple connector using the AWS IoT Data plane."""

    id = "aws_iot_core"
    name = "AWS IoT Core"

    def __init__(self, region: str, topic: str, endpoint: Optional[str] = None, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.region = region
        self.topic = topic
        self.endpoint = endpoint
        if boto3:
            params: Dict[str, Any] = {"region_name": self.region}
            if self.endpoint:
                params["endpoint_url"] = self.endpoint
            self.client = boto3.client("iot-data", **params)
        else:  # pragma: no cover - dependency may be missing
            self.client = None

    async def send_message(self, message: str) -> Any:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        return self.client.publish(topic=self.topic, qos=1, payload=message)

    async def listen_and_process(self) -> None:
        """Listening is not implemented for AWS IoT Core."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
