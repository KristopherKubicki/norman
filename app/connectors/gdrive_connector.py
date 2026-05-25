"""Connector for Google Drive webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class GDriveConnector(WebhookOnlyConnector):
    id = "gdrive"
    name = "Google Drive"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        file = message.get("file") or {}
        text = file.get("name") or "Drive change"
        summary_parts = ["gdrive"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "file_id": file.get("id"),
            "mime_type": file.get("mimeType"),
            "owner": (file.get("owners") or [{}])[0].get("emailAddress")
            if isinstance(file.get("owners"), list)
            else None,
            "text_summary": summary,
        }
