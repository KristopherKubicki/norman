"""Connector for Datadog webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class DatadogConnector(WebhookOnlyConnector):
    id = "datadog"
    name = "Datadog"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        alert = message.get("alert") or message
        text = alert.get("title") or alert.get("message") or ""
        status = alert.get("status")
        summary_parts = ["datadog"]
        if status:
            summary_parts.append(str(status))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "alert_id": alert.get("id") or alert.get("alert_id"),
            "status": status,
            "priority": alert.get("priority"),
            "tags": alert.get("tags"),
            "text_summary": summary,
        }
