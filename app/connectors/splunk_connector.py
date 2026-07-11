"""Connector for Splunk webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class SplunkConnector(WebhookOnlyConnector):
    id = "splunk"
    name = "Splunk"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        result = message.get("result") or message
        text = result.get("message") or result.get("title") or ""
        severity = result.get("severity") or result.get("level")
        summary_parts = ["splunk"]
        if severity:
            summary_parts.append(str(severity))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "source": result.get("source"),
            "severity": severity,
            "host": result.get("host"),
            "sourcetype": result.get("sourcetype"),
            "text_summary": summary,
        }
