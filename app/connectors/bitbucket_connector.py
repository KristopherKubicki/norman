"""Connector for Bitbucket webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class BitbucketConnector(WebhookOnlyConnector):
    id = "bitbucket"
    name = "Bitbucket"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        event = message.get("event") or message
        repo = (event.get("repository") or {}).get("full_name")
        text = event.get("event") or event.get("type") or ""
        summary_parts = ["bitbucket"]
        if repo:
            summary_parts.append(repo)
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "repo": repo,
            "actor": (event.get("actor") or {}).get("display_name"),
            "text_summary": summary,
        }
