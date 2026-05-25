"""Connector for ntfy webhook payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class NtfyConnector(WebhookOnlyConnector):
    id = "ntfy"
    name = "ntfy"

    def __init__(
        self,
        webhook_url: str = "",
        topic: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.topic = topic

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "ntfy")
            normalized.setdefault("sensor_type", "push_notifications")
            return normalized

        topic = _clean(message.get("topic") or self.topic)
        title = _clean(message.get("title"))
        body = _clean(message.get("message") or message.get("text"))
        priority = message.get("priority")
        tags = message.get("tags") if isinstance(message.get("tags"), list) else []

        text = body or title or "ntfy event"
        summary = " - ".join(
            part
            for part in (
                "ntfy",
                topic,
                title,
                str(priority) if priority is not None else "",
            )
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "ntfy",
            "topic": topic or None,
            "title": title or None,
            "priority": priority,
            "tags": tags,
            "event_time": message.get("time"),
            "signal_class": "passive",
            "passive_source": "ntfy",
            "sensor_type": "push_notifications",
        }
