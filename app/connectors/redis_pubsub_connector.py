from typing import Optional

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from .base_connector import BaseConnector


class RedisPubSubConnector(BaseConnector):
    """Connector using Redis publish/subscribe."""

    id = "redis_pubsub"
    name = "Redis Pub/Sub"

    def __init__(self, host: str = "localhost", port: int = 6379, channel: str = "norman", config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.channel = channel
        self._client: Optional[redis.Redis] = redis.Redis(host=self.host, port=self.port) if redis else None

    def connect(self) -> None:
        if not redis:
            raise RuntimeError("redis-py not installed")
        if not self._client:
            self._client = redis.Redis(host=self.host, port=self.port)

    def disconnect(self) -> None:
        # redis-py does not require explicit disconnect for basic clients
        pass

    def send_message(self, message: str) -> None:
        if not redis:
            raise RuntimeError("redis-py not installed")
        if not self._client:
            self.connect()
        assert self._client is not None
        self._client.publish(self.channel, message)

    async def listen_and_process(self) -> None:
        """Listening not implemented."""
        return None

    async def process_incoming(self, message: str) -> str:
        return message
