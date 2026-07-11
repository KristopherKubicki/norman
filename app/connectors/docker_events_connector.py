"""Connector for Docker event stream payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class DockerEventsConnector(WebhookOnlyConnector):
    id = "docker_events"
    name = "Docker Events"

    def __init__(
        self,
        webhook_url: str = "",
        host: str = "",
        event_filter: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.host = host
        self.event_filter = event_filter

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "docker_events")
            normalized.setdefault("sensor_type", "containers")
            return normalized

        actor = message.get("Actor") if isinstance(message.get("Actor"), dict) else {}
        attrs = (
            actor.get("Attributes") if isinstance(actor.get("Attributes"), dict) else {}
        )

        kind = _clean(message.get("Type") or message.get("type"))
        action = _clean(message.get("Action") or message.get("action"))
        container = _clean(
            attrs.get("name")
            or message.get("container")
            or message.get("container_name")
            or message.get("name")
        )
        image = _clean(attrs.get("image") or message.get("image"))
        host = _clean(message.get("host") or self.host)
        event_id = _clean(
            message.get("id") or actor.get("ID") or message.get("container_id")
        )

        text = _clean(
            message.get("message")
            or message.get("summary")
            or message.get("description")
            or message.get("text")
        )
        if not text:
            text = " ".join(
                part for part in (kind, action, container, image) if part
            ).strip()
        if not text:
            text = "docker event"

        summary = " - ".join(
            part for part in ("docker_events", host, kind, action, container) if part
        )

        return {
            "text": text,
            "text_summary": summary or "docker_events",
            "event_type": kind or None,
            "action": action or None,
            "container": container or None,
            "image": image or None,
            "host": host or None,
            "event_id": event_id or None,
            "event_time": message.get("time") or message.get("timeNano"),
            "signal_class": "passive",
            "passive_source": "docker_events",
            "sensor_type": "containers",
        }
