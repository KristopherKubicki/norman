"""Connector for CircleCI webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class CircleCIConnector(WebhookOnlyConnector):
    id = "circleci"
    name = "CircleCI"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        pipeline = message.get("pipeline") or {}
        vcs = pipeline.get("vcs") or {}
        commit = vcs.get("commit") or {}
        text = commit.get("subject") or vcs.get("branch") or "CircleCI event"
        state = message.get("status") or pipeline.get("state")
        summary_parts = ["circleci"]
        if state:
            summary_parts.append(str(state))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "pipeline_id": pipeline.get("id"),
            "state": state,
            "branch": vcs.get("branch"),
            "repo": (vcs.get("origin_repository") or {}).get("name"),
            "text_summary": summary,
        }
