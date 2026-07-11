"""Connector for Opsgenie webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class OpsgenieConnector(WebhookOnlyConnector):
    id = "opsgenie"
    name = "Opsgenie"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        alert = message.get("alert") or {}
        text = alert.get("message") or alert.get("description") or ""
        summary_parts = ["opsgenie"]
        if alert.get("status"):
            summary_parts.append(str(alert.get("status")))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "alert_id": alert.get("alertId") or alert.get("id"),
            "status": alert.get("status"),
            "priority": alert.get("priority"),
            "owner": alert.get("owner"),
            "team": alert.get("team"),
            "text_summary": summary,
        }
