"""Connector for Airtable webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class AirtableConnector(WebhookOnlyConnector):
    id = "airtable"
    name = "Airtable"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        record = message.get("record") or {}
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
        text = fields.get("Name") or ""
        table = message.get("table") or message.get("tableId")
        summary_parts = ["airtable"]
        if table:
            summary_parts.append(str(table))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "record_id": record.get("id") or message.get("recordId"),
            "table": table,
            "base": message.get("baseId") or message.get("base"),
            "text_summary": summary,
        }
