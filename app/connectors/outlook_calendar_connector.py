"""Connector for Outlook Calendar webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class OutlookCalendarConnector(WebhookOnlyConnector):
    id = "outlook_calendar"
    name = "Outlook Calendar"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or message
        return {
            "text": event.get("subject") or event.get("bodyPreview") or "",
            "event_id": event.get("id"),
            "status": event.get("showAs") or event.get("status"),
        }
