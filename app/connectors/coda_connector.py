"""Connector for Coda webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class CodaConnector(WebhookOnlyConnector):
    id = "coda"
    name = "Coda"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or message
        text = event.get("type") or event.get("resource", {}).get("name", "")
        summary_parts = ["coda"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "doc_id": event.get("docId") or event.get("doc_id"),
            "event_type": event.get("type"),
            "table_id": event.get("tableId") or event.get("table_id"),
            "text_summary": summary,
        }
