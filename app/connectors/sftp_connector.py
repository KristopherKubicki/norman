"""Connector for SFTP file events."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class SFTPConnector(WebhookOnlyConnector):
    id = "sftp"
    name = "SFTP"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        text = message.get("path") or "SFTP event"
        event = message.get("event")
        summary_parts = ["sftp"]
        if event:
            summary_parts.append(str(event))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "path": message.get("path"),
            "event": event,
            "text_summary": summary,
        }
