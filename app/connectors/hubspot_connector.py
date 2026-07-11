"""Connector for HubSpot webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class HubSpotConnector(WebhookOnlyConnector):
    id = "hubspot"
    name = "HubSpot"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if isinstance(message, list) and message:
            event = message[0]
        elif isinstance(message, dict):
            event = message
        else:
            return {"raw": message}
        text = event.get("propertyValue") or event.get("propertyName") or ""
        summary_parts = ["hubspot"]
        if event.get("subscriptionType"):
            summary_parts.append(event.get("subscriptionType"))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "object_id": event.get("objectId"),
            "subscription_type": event.get("subscriptionType"),
            "event_id": event.get("eventId"),
            "text_summary": summary,
        }
