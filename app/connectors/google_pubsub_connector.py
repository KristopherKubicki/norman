"""Connector for publishing messages to Google Pub/Sub."""

from typing import Any, Dict, Optional

try:
    from google.cloud import pubsub_v1
except ImportError:  # pragma: no cover - optional dependency
    pubsub_v1 = None

from .base_connector import BaseConnector


class GooglePubSubConnector(BaseConnector):
    """Simple connector using the google-cloud-pubsub client."""

    id = "google_pubsub"
    name = "Google Pub/Sub"

    def __init__(
        self,
        project_id: str,
        topic_id: str,
        credentials_path: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.project_id = project_id
        self.topic_id = topic_id
        self.credentials_path = credentials_path
        if pubsub_v1:
            if self.credentials_path:
                self.publisher = pubsub_v1.PublisherClient.from_service_account_file(
                    self.credentials_path
                )
            else:
                self.publisher = pubsub_v1.PublisherClient()
        else:  # pragma: no cover - dependency may be missing
            self.publisher = None

    async def send_message(self, message: str) -> Any:
        if not pubsub_v1:
            raise RuntimeError("google-cloud-pubsub not installed")
        topic_path = self.publisher.topic_path(self.project_id, self.topic_id)
        future = self.publisher.publish(topic_path, message.encode())
        return future.result()

    async def listen_and_process(self) -> None:
        """Pub/Sub listening not implemented."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
