"""Connector for Zendesk webhooks."""

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


class ZendeskConnector(WebhookOnlyConnector):
    id = "zendesk"
    name = "Zendesk"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        ticket = message.get("ticket") or {}
        comment = message.get("comment") or {}
        text = comment.get("body") or ticket.get("subject") or ""
        summary_parts = ["zendesk"]
        if ticket.get("status"):
            summary_parts.append(ticket.get("status"))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "ticket_id": ticket.get("id"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
            "requester": ticket.get("requester"),
            "assignee": ticket.get("assignee"),
            "brand": ticket.get("brand"),
            "via": ticket.get("via"),
            "text_summary": summary,
        }
