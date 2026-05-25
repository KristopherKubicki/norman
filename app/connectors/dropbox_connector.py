"""Connector for Dropbox webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class DropboxConnector(WebhookOnlyConnector):
    id = "dropbox"
    name = "Dropbox"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        delta = message.get("delta") or message
        text = delta.get("path") or "Dropbox change"
        event = delta.get("event") or message.get("type")
        summary_parts = ["dropbox"]
        if event:
            summary_parts.append(str(event))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "path": delta.get("path"),
            "event": event,
            "text_summary": summary,
        }
