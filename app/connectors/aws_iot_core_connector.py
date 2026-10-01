"""Connector for publishing and subscribing via AWS IoT Core."""

from typing import Any, Dict, Optional
import asyncio
from urllib.parse import urlparse

try:
    import boto3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None

try:  # pragma: no cover - optional dependency
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - optional dependency
    mqtt = None

from .base_connector import BaseConnector


def _is_configured_value(value: Optional[str]) -> bool:
    """Return whether an AWS setting is a real configured value."""

    return bool(value and value.strip() and not value.strip().startswith("your_"))


class AWSIoTCoreConnector(BaseConnector):
    """Connector for AWS IoT Core using boto3 and MQTT."""

    id = "aws_iot_core"
    name = "AWS IoT Core"

    def __init__(
        self,
        region: str,
        topic: str,
        endpoint: Optional[str] = None,
        client_id: Optional[str] = None,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        ca_path: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.region = region
        self.topic = topic
        self.endpoint = endpoint
        self.client_id = client_id
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path

        if boto3 and _is_configured_value(self.region):
            params: Dict[str, Any] = {"region_name": self.region}
            if self.endpoint:
                params["endpoint_url"] = self.endpoint
            self.client = boto3.client("iot-data", **params)
        else:  # pragma: no cover - dependency may be missing
            self.client = None

        if mqtt:
            self.mqtt_client = mqtt.Client(client_id=self.client_id or "")
            if (
                self.cert_path
                and self.key_path
                and self.ca_path
                and not str(self.cert_path).startswith("your_")
            ):
                self.mqtt_client.tls_set(
                    ca_certs=self.ca_path,
                    certfile=self.cert_path,
                    keyfile=self.key_path,
                )
            self.mqtt_client.on_message = self._on_message
        else:  # pragma: no cover - optional dependency may be missing
            self.mqtt_client = None

    async def send_message(self, message: str) -> Any:
        if not boto3:
            raise RuntimeError("boto3 not installed")
        if self.client is None:
            raise RuntimeError("AWS IoT Core region is not configured")
        return self.client.publish(topic=self.topic, qos=1, payload=message)

    def _parse_host(self) -> Optional[str]:
        if not self.endpoint:
            return None
        parsed = urlparse(self.endpoint)
        return parsed.hostname or parsed.path

    async def listen_and_process(self) -> None:
        if not mqtt:
            raise RuntimeError("paho-mqtt not installed")

        host = self._parse_host()
        if not host:
            raise RuntimeError("endpoint required for listening")

        self.mqtt_client.connect(host, 8883)
        self.mqtt_client.subscribe(self.topic)
        self.mqtt_client.loop_start()
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        if not isinstance(message, dict):
            text = str(message)
            summary = f"iot • {text}" if text else "iot"
            return {"text": text, "text_summary": summary}
        text = message.get("message") or message.get("text") or ""
        summary_parts = ["iot"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "topic": message.get("topic") or self.topic,
            "text_summary": summary,
        }

    def _on_message(self, client, userdata, msg) -> None:  # pragma: no cover - callback
        asyncio.create_task(self.process_incoming(msg.payload.decode()))

    def is_connected(self) -> bool:
        """Return ``True`` if IoT endpoint can be resolved."""
        if not super().is_connected():
            return False
        if not boto3 or self.client is None:
            return False
        try:
            resp = self.client.describe_endpoint(endpointType="iot:Data-ATS")
            return bool(resp.get("endpointAddress"))
        except Exception:
            return False
