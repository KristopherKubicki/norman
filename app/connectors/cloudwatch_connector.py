"""Connector for AWS CloudWatch webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class CloudWatchConnector(WebhookOnlyConnector):
    id = "cloudwatch"
    name = "AWS CloudWatch"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        alarm = message.get("AlarmName") or message.get("alarmName") or ""
        reason = message.get("NewStateReason") or message.get("newStateReason") or ""
        state = message.get("NewStateValue") or message.get("newStateValue")
        text = alarm or reason or "CloudWatch alarm"
        summary_parts = ["cloudwatch"]
        if state:
            summary_parts.append(str(state))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "alarm_name": alarm,
            "state": state,
            "reason": reason,
            "alarm_arn": message.get("AlarmArn") or message.get("alarmArn"),
            "text_summary": summary,
        }
