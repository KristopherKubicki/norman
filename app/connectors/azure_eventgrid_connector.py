"""Connector for publishing events to Azure Event Grid."""

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
    """Connector using Azure EventGridPublisherClient."""

    id = "azure_eventgrid"
    name = "Azure Event Grid"

    def __init__(self, endpoint: str, key: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.key = key
        if EventGridPublisherClient and AzureKeyCredential:
            credential = AzureKeyCredential(self.key)
            self.client = EventGridPublisherClient(self.endpoint, credential)
        else:  # pragma: no cover - dependency may be missing
            self.client = None

    async def send_message(self, message: Dict[str, Any]) -> Any:
        if not EventGridPublisherClient:
            raise RuntimeError("azure-eventgrid not installed")
        event = EventGridEvent(subject="norman", event_type="Message", data=message, data_version="1.0")
        self.client.send([event])
        return "ok"

    async def listen_and_process(self) -> None:
        """Listening is not implemented for Event Grid."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return message
