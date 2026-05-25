"""Connector for Trello webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class TrelloConnector(WebhookOnlyConnector):
    id = "trello"
    name = "Trello"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        action = message.get("action") or {}
        data = action.get("data") or {}
        card = data.get("card") or {}
        text = action.get("type") or card.get("name") or ""
        summary_parts = ["trello"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "card_id": card.get("id"),
            "board_id": (data.get("board") or {}).get("id"),
            "list_id": (data.get("list") or {}).get("id"),
            "text_summary": summary,
        }
