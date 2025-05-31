import json
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    BotoCoreError = ClientError = Exception

from .base_connector import BaseConnector


class AWSIoTCoreConnector(BaseConnector):
    """Connector that publishes messages to AWS IoT Core."""

    id = "aws_iot_core"
    name = "AWS IoT Core"

    def __init__(
        self,
        topic: str,
        region_name: str = "us-east-1",
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.topic = topic
        if boto3:
            self.client = boto3.client(
                "iot-data",
                region_name=region_name,
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
            )
        else:  # pragma: no cover - library may not be installed
            self.client = None

    async def send_message(self, message: str) -> Optional[str]:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        try:
            resp = self.client.publish(topic=self.topic, qos=0, payload=message)
            return json.dumps(resp)
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover - network
            print(f"Error publishing to AWS IoT Core: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """AWS IoT Core connector does not receive messages."""
        return None

    async def process_incoming(self, message: str) -> str:
        await self.send_message(message)
        return message
