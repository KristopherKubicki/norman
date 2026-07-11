"""Connector for Notion webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class NotionConnector(WebhookOnlyConnector):
    id = "notion"
    name = "Notion"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        data = message.get("data") or {}
        page = data.get("page") or {}
        text = page.get("title") or data.get("name") or ""
        action = message.get("type") or data.get("type")
        summary_parts = ["notion"]
        if action:
            summary_parts.append(action)
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "page_id": page.get("id") or data.get("id"),
            "type": action,
            "text_summary": summary,
        }
