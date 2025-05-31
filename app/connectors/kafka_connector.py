"""Connector for sending messages to Kafka or Redpanda."""

from typing import Optional

try:
    from confluent_kafka import Producer
except ImportError:  # pragma: no cover - optional dependency
    Producer = None  # type: ignore

from .base_connector import BaseConnector


class KafkaConnector(BaseConnector):
    """Minimal connector using ``confluent-kafka``."""

    id = "kafka"
    name = "Kafka/Redpanda"

    def __init__(self, bootstrap_servers: str = "localhost:9092", topic: str = "norman", config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self._producer: Optional[Producer] = Producer({"bootstrap.servers": self.bootstrap_servers}) if Producer else None

    def send_message(self, message: str) -> Optional[str]:
        if not Producer:
            raise RuntimeError("confluent-kafka not installed")
        if not self._producer:
            self._producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        self._producer.produce(self.topic, value=message.encode())
        self._producer.flush()
        return "ok"

    async def listen_and_process(self) -> None:
        """Listening for messages is not implemented."""
        return None

    async def process_incoming(self, message: str) -> str:
        return message
