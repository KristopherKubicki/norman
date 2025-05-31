from typing import Optional

try:
    import pika
except ImportError:  # pragma: no cover - optional dependency
    pika = None

from .base_connector import BaseConnector


class AMQPConnector(BaseConnector):
    """Basic connector for AMQP brokers like RabbitMQ."""

    id = "amqp"
    name = "AMQP"

    def __init__(self, url: str, queue: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.url = url
        self.queue = queue
        self._connection: Optional[pika.BlockingConnection] = None if pika else None
        self._channel: Optional[pika.adapters.blocking_connection.BlockingChannel] = None

    def connect(self) -> None:
        if not pika:
            raise RuntimeError("pika not installed")
        self._connection = pika.BlockingConnection(pika.URLParameters(self.url))
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=self.queue, durable=True)

    def disconnect(self) -> None:
        if self._connection:
            try:
                self._connection.close()
            finally:
                self._connection = None
                self._channel = None

    def send_message(self, message: str) -> None:
        if not pika:
            raise RuntimeError("pika not installed")
        if not self._channel:
            self.connect()
        assert self._channel is not None
        self._channel.basic_publish(exchange="", routing_key=self.queue, body=message.encode())

    async def listen_and_process(self) -> None:
        """Listening not implemented."""
        return None

    async def process_incoming(self, message: str) -> str:
        return message
