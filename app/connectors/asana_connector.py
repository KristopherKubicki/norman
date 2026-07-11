"""Connector for Asana webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class AsanaConnector(WebhookOnlyConnector):
    id = "asana"
    name = "Asana"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if isinstance(message, list) and message:
            event = message[0]
        elif isinstance(message, dict):
            event = message
        else:
            return {"raw": message}
        resource = (
            event.get("resource") if isinstance(event.get("resource"), dict) else {}
        )
        text = resource.get("name") or ""
        action = event.get("action")
        summary_parts = ["asana"]
        if action:
            summary_parts.append(action)
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "resource_id": resource.get("gid"),
            "action": action,
            "resource_type": event.get("resource", {}).get("resource_type")
            if isinstance(event.get("resource"), dict)
            else None,
            "text_summary": summary,
        }
