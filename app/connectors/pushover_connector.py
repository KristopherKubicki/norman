"""Connector for Pushover webhook payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class PushoverConnector(WebhookOnlyConnector):
    id = "pushover"
    name = "Pushover"

    def __init__(
        self,
        webhook_url: str = "",
        user_key: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.user_key = user_key

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "pushover")
            normalized.setdefault("sensor_type", "push_notifications")
            return normalized

        title = _clean(message.get("title"))
        body = _clean(message.get("message") or message.get("text"))
        priority = message.get("priority")
        user = _clean(message.get("user") or message.get("user_key") or self.user_key)
        device = _clean(message.get("device"))

        text = body or title or "pushover event"
        summary = " - ".join(
            part
            for part in (
                "pushover",
                user,
                title,
                str(priority) if priority is not None else "",
            )
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "pushover",
            "title": title or None,
            "priority": priority,
            "user": user or None,
            "device": device or None,
            "url": message.get("url"),
            "event_time": message.get("timestamp") or message.get("time"),
            "signal_class": "passive",
            "passive_source": "pushover",
            "sensor_type": "push_notifications",
        }
