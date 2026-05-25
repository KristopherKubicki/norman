"""Connector for Freshdesk webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class FreshdeskConnector(WebhookOnlyConnector):
    id = "freshdesk"
    name = "Freshdesk"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        ticket = message.get("ticket") or {}
        requester = message.get("requester") or {}
        text = ticket.get("description_text") or ticket.get("subject") or ""
        summary_parts = ["freshdesk"]
        if ticket.get("status"):
            summary_parts.append(str(ticket.get("status")))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "ticket_id": ticket.get("id"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
            "requester": requester.get("email") or requester.get("name"),
            "group": ticket.get("group_id"),
            "source": ticket.get("source"),
            "text_summary": summary,
        }
