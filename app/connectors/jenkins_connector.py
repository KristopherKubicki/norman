"""Connector for Jenkins webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class JenkinsConnector(WebhookOnlyConnector):
    id = "jenkins"
    name = "Jenkins"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        build = message.get("build") or {}
        text = build.get("full_url") or build.get("url") or "Jenkins build"
        status = build.get("status") or build.get("result")
        summary_parts = ["jenkins"]
        if status:
            summary_parts.append(str(status))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "job_name": build.get("full_url") or message.get("name"),
            "status": status,
            "build_number": build.get("number"),
            "text_summary": summary,
        }
