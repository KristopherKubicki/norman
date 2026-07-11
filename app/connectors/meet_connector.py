"""Connector for Google Meet webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class MeetConnector(WebhookOnlyConnector):
    id = "meet"
    name = "Google Meet"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or message
        return {
            "text": event.get("summary") or event.get("meetingCode") or "",
            "meeting_id": event.get("meetingId") or event.get("conferenceId"),
            "status": event.get("status"),
        }
