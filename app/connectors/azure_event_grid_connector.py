from typing import Any, Dict, Optional

try:
    from azure.eventgrid import EventGridPublisherClient, EventGridEvent
    from azure.core.credentials import AzureKeyCredential
except ImportError:  # pragma: no cover - optional dependency
    EventGridPublisherClient = None
    EventGridEvent = None
    AzureKeyCredential = None

from .base_connector import BaseConnector


class AzureEventGridConnector(BaseConnector):
    """Connector for sending events to Azure Event Grid."""

    id = "azure_event_grid"
    name = "Azure Event Grid"

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.access_key = access_key
        if EventGridPublisherClient:
            credential = AzureKeyCredential(access_key)
            self.client = EventGridPublisherClient(endpoint, credential)
        else:  # pragma: no cover
            self.client = None

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        if not EventGridPublisherClient:
            raise RuntimeError("azure-eventgrid not installed")
        event = EventGridEvent(
            subject=message.get("subject", "Norman"),
            data=message.get("data", {}),
            event_type=message.get("event_type", "Norman.Event"),
            data_version=message.get("data_version", "1.0"),
        )
        try:
            self.client.send([event])
            return "sent"
        except Exception as exc:  # pragma: no cover - network
            print(f"Error sending to Event Grid: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """Event Grid connector does not receive messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        await self.send_message(message)
        return message
