"""Connector for New Relic webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class NewRelicConnector(WebhookOnlyConnector):
    id = "newrelic"
    name = "New Relic"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        incident = message.get("incident") or message
        text = incident.get("title") or incident.get("description") or ""
        status = incident.get("status")
        summary_parts = ["newrelic"]
        if status:
            summary_parts.append(str(status))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "incident_id": incident.get("id"),
            "status": status,
            "severity": incident.get("severity"),
            "opened_at": incident.get("opened_at") or incident.get("openedAt"),
            "text_summary": summary,
        }
