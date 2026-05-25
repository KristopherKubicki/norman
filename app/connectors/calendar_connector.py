"""Connector for Google Calendar webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class CalendarConnector(WebhookOnlyConnector):
    id = "calendar"
    name = "Google Calendar"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or message
        return {
            "text": event.get("summary") or event.get("description") or "",
            "event_id": event.get("id"),
            "status": event.get("status"),
        }
