"""Connector for Help Scout webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class HelpScoutConnector(WebhookOnlyConnector):
    id = "help_scout"
    name = "Help Scout"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or {}
        convo = message.get("conversation") or {}
        customer = message.get("customer") or {}
        text = event.get("body") or convo.get("subject") or ""
        summary_parts = ["helpscout"]
        if convo.get("status"):
            summary_parts.append(str(convo.get("status")))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "conversation_id": convo.get("id"),
            "status": convo.get("status"),
            "customer": customer.get("email") or customer.get("name"),
            "mailbox": convo.get("mailbox", {}).get("name")
            if isinstance(convo.get("mailbox"), dict)
            else convo.get("mailbox"),
            "text_summary": summary,
        }
