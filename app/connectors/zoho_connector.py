"""Connector for Zoho CRM webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class ZohoConnector(WebhookOnlyConnector):
    id = "zoho"
    name = "Zoho CRM"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        data = message.get("data") or message
        if isinstance(data, list) and data:
            data = data[0]
        return {
            "text": data.get("Name") or data.get("Subject") or "",
            "record_id": data.get("id"),
            "module": message.get("module") or data.get("module"),
        }
