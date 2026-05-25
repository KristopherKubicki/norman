"""Connector for Pipedrive webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class PipedriveConnector(WebhookOnlyConnector):
    id = "pipedrive"
    name = "Pipedrive"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        current = message.get("current") or {}
        text = current.get("title") or current.get("name") or ""
        event = message.get("event")
        summary_parts = ["pipedrive"]
        if event:
            summary_parts.append(str(event))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "deal_id": current.get("id") or message.get("id"),
            "event": event,
            "owner_id": current.get("owner_id"),
            "status": current.get("status"),
            "text_summary": summary,
        }
