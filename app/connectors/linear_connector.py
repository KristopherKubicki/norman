"""Connector for Linear webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class LinearConnector(WebhookOnlyConnector):
    id = "linear"
    name = "Linear"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        data = message.get("data") or {}
        issue = data.get("issue") or {}
        text = issue.get("title") or issue.get("description") or ""
        state = (
            issue.get("state", {}).get("name")
            if isinstance(issue.get("state"), dict)
            else issue.get("state")
        )
        summary_parts = ["linear"]
        if state:
            summary_parts.append(state)
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "issue_id": issue.get("id"),
            "state": state,
            "team": (issue.get("team") or {}).get("name"),
            "assignee": (issue.get("assignee") or {}).get("name"),
            "text_summary": summary,
        }
