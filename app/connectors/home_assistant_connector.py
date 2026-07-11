"""Connector for Home Assistant webhook and event payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class HomeAssistantConnector(WebhookOnlyConnector):
    id = "home_assistant"
    name = "Home Assistant"

    def __init__(
        self,
        webhook_url: str = "",
        instance: str = "",
        event_filter: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.instance = instance
        self.event_filter = event_filter

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "home_assistant")
            normalized.setdefault("sensor_type", "home_automation")
            return normalized

        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        new_state = (
            data.get("new_state") if isinstance(data.get("new_state"), dict) else {}
        )
        attributes = (
            new_state.get("attributes")
            if isinstance(new_state.get("attributes"), dict)
            else {}
        )

        event_type = _clean(message.get("event_type") or message.get("type"))
        entity_id = _clean(data.get("entity_id") or message.get("entity_id"))
        friendly_name = _clean(
            attributes.get("friendly_name") or message.get("friendly_name")
        )
        state = _clean(new_state.get("state") or message.get("state"))

        text = _clean(
            message.get("text")
            or message.get("summary")
            or message.get("message")
            or message.get("description")
        )
        if not text:
            subject = friendly_name or entity_id
            text = " ".join(
                part for part in (subject, event_type, state) if part
            ).strip()
        if not text:
            text = "home assistant event"

        summary = " - ".join(
            part
            for part in (
                "home_assistant",
                friendly_name or entity_id,
                event_type,
                state,
            )
            if part
        )

        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""

        return {
            "text": text,
            "text_summary": summary or "home_assistant",
            "event_type": event_type or None,
            "entity_id": entity_id or None,
            "entity_name": friendly_name or None,
            "state": state or None,
            "domain": domain or None,
            "event_time": message.get("time_fired") or message.get("timestamp"),
            "signal_class": "passive",
            "passive_source": "home_assistant",
            "sensor_type": "home_automation",
        }
