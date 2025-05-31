import asyncio
from typing import Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - library may not be installed for tests
    mqtt = None

from .base_connector import BaseConnector


class MQTTConnector(BaseConnector):
    """Simple connector for MQTT brokers."""

    id = "mqtt"
    name = "MQTT"

    def __init__(
        self,
        host: str,
        port: int = 1883,
        topic: str = "norman",
        username: Optional[str] = None,
        password: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.topic = topic
        self.username = username
        self.password = password
        if mqtt:
            self.client = mqtt.Client()
            if username and password:
                self.client.username_pw_set(username, password)
            self.client.on_message = self._on_message
        else:  # pragma: no cover - tests may run without mqtt installed
            self.client = None

    async def send_message(self, message: str) -> None:
        if not mqtt:
            raise RuntimeError("paho-mqtt not installed")
        self.client.connect(self.host, self.port)
        self.client.publish(self.topic, message)
        self.client.disconnect()

    async def listen_and_process(self) -> None:
        if not mqtt:
            raise RuntimeError("paho-mqtt not installed")
        self.client.connect(self.host, self.port)
        self.client.subscribe(self.topic)
        self.client.loop_start()
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            self.client.loop_stop()
            self.client.disconnect()

    async def process_incoming(self, message: str):
        print(f"MQTT received: {message}")

    def _on_message(self, client, userdata, msg):  # pragma: no cover - callback
        asyncio.create_task(self.process_incoming(msg.payload.decode()))
