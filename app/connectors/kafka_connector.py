"""Connector for sending messages to Kafka or Redpanda."""

import asyncio
from typing import Optional

try:
    from confluent_kafka import Producer, Consumer
except ImportError:  # pragma: no cover - optional dependency
    Producer = None  # type: ignore
    Consumer = None  # type: ignore

from .base_connector import BaseConnector


class KafkaConnector(BaseConnector):
    """Minimal connector using ``confluent-kafka``."""

    id = "kafka"
    name = "Kafka/Redpanda"

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        topic: str = "norman",
        group_id: str = "norman",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self._producer: Optional[Producer] = (
            Producer({"bootstrap.servers": self.bootstrap_servers}) if Producer else None
        )
        self._consumer_conf = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
        }
        self._consumer: Optional[Consumer] = None

    async def disconnect(self) -> None:
        if self._consumer:
            self._consumer.close()
            self._consumer = None

    def send_message(self, message: str) -> Optional[str]:
        if not Producer:
            raise RuntimeError("confluent-kafka not installed")
        if not self._producer:
            self._producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        self._producer.produce(self.topic, value=message.encode())
        self._producer.flush()
        return "ok"

    async def listen_and_process(self) -> None:
        """Consume messages from ``topic`` and process them indefinitely."""

        if not Consumer:
            raise RuntimeError("confluent-kafka not installed")
        if not self._consumer:
            self._consumer = Consumer(self._consumer_conf)
            self._consumer.subscribe([self.topic])

        assert self._consumer is not None
        while True:  # pragma: no cover - run forever
            msg = self._consumer.poll(0.1)
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            if msg.error():
                continue
            payload = msg.value().decode()
            result = self.process_incoming(payload)
            if asyncio.iscoroutine(result):
                await result

    async def process_incoming(self, message: str) -> str:
        return message
