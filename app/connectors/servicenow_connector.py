"""Connector for ServiceNow webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class ServiceNowConnector(WebhookOnlyConnector):
    id = "servicenow"
    name = "ServiceNow"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        record = message.get("record") or message
        text = record.get("short_description") or record.get("description") or ""
        state = record.get("state")
        summary_parts = ["servicenow"]
        if state:
            summary_parts.append(str(state))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "record_id": record.get("sys_id") or record.get("number"),
            "state": state,
            "priority": record.get("priority"),
            "assignment_group": record.get("assignment_group"),
            "caller": record.get("caller_id"),
            "text_summary": summary,
        }
