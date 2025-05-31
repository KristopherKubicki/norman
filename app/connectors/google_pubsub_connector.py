from typing import Optional

try:
    from google.cloud import pubsub_v1
except ImportError:  # pragma: no cover - optional dependency
    pubsub_v1 = None

from .base_connector import BaseConnector


class GooglePubSubConnector(BaseConnector):
    """Connector that publishes messages to Google Pub/Sub."""

    id = "google_pubsub"
    name = "Google Pub/Sub"

    def __init__(
        self,
        project_id: str,
        topic_id: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.project_id = project_id
        self.topic_id = topic_id
        if pubsub_v1:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(project_id, topic_id)
        else:  # pragma: no cover
            self.publisher = None
            self.topic_path = None

    async def send_message(self, message: str) -> None:
        if not pubsub_v1:
            raise RuntimeError("google-cloud-pubsub not installed")
        self.publisher.publish(self.topic_path, message.encode())

    async def listen_and_process(self) -> None:
        """Pub/Sub connector does not support inbound messages."""
        return None

    async def process_incoming(self, message: str) -> str:
        await self.send_message(message)
        return message
